from __future__ import annotations
import asyncio, base64, binascii, hmac, logging, os, tempfile
from pathlib import Path
from typing import Any
from deep_translator import GoogleTranslator, MyMemoryTranslator
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from faster_whisper import WhisperModel
from pydantic import BaseModel, Field

logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"))
log=logging.getLogger("vietsub")
TOKEN=os.getenv("INTERNAL_API_TOKEN","")
MODEL_SIZE=os.getenv("MODEL_SIZE","small")
COMPUTE_TYPE=os.getenv("COMPUTE_TYPE","int8")
MAX_AUDIO_BYTES=int(os.getenv("MAX_AUDIO_BYTES",str(8*1024*1024)))
MAX_TEXT_CHARS=int(os.getenv("MAX_TEXT_CHARS","5000"))
TRANSLATION_TIMEOUT=float(os.getenv("TRANSLATION_TIMEOUT_SECONDS","12"))
ORIGINS={x.strip().rstrip("/") for x in os.getenv("ALLOWED_ORIGINS","http://localhost:5173").split(",") if x.strip()}
app=FastAPI(title="Vietsub Pro Realtime API",version="1.0.0")
model: WhisperModel|None=None
model_lock=asyncio.Lock()
inference_lock=asyncio.Semaphore(max(1,int(os.getenv("MAX_CONCURRENT_INFERENCE","1"))))

class TranslateBody(BaseModel):
    text: str=Field(min_length=1,max_length=MAX_TEXT_CHARS)
    source_lang: str="auto"
    target_lang: str="vi"

def authorized(value: str|None)->bool:
    return bool(TOKEN and value and hmac.compare_digest(value.encode(),TOKEN.encode()))

def get_model()->WhisperModel:
    global model
    if model is None:
        log.info("Loading Faster-Whisper model=%s on CPU",MODEL_SIZE)
        model=WhisperModel(MODEL_SIZE,device="cpu",compute_type=COMPUTE_TYPE)
    return model

async def warm_model():
    async with model_lock:
        if model is None: await asyncio.to_thread(get_model)

def translate_sync(text:str,source:str,target:str)->str:
    if not text.strip(): return text
    try: return MyMemoryTranslator(source=source if source!="auto" else "auto",target=target).translate(text) or text
    except Exception as exc:
        log.warning("MyMemory failed: %s",type(exc).__name__)
        try: return GoogleTranslator(source="auto",target=target).translate(text) or text
        except Exception as fallback:
            log.warning("Google translation failed: %s",type(fallback).__name__)
            return text

async def translate(text:str,source:str,target:str)->str:
    return await asyncio.wait_for(asyncio.to_thread(translate_sync,text,source,target),timeout=TRANSLATION_TIMEOUT)

def transcribe_sync(audio:bytes,ext:str,source:str,target:str)->dict[str,Any]:
    suffix="."+ext if ext.isalnum() else ".wav"
    tmp=None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix,delete=False) as f: f.write(audio); tmp=f.name
        segments,info=get_model().transcribe(tmp,language=None if source=="auto" else source,vad_filter=True,beam_size=1)
        result=[]
        for seg in segments:
            original=(seg.text or "").strip()
            result.append({"start":round(float(seg.start),3),"end":round(float(seg.end),3),
                           "original":original,"translated":translate_sync(original,info.language or source,target) if original else ""})
        return {"detected_lang":info.language,"duration":info.duration,"segments":result}
    finally:
        if tmp:
            try: Path(tmp).unlink(missing_ok=True)
            except OSError: pass

@app.get("/healthz")
async def healthz(): return {"status":"ok","service":"vietsub-realtime","model_loaded":model is not None,"device":"cpu"}

@app.get("/api/v1/meta")
async def meta(): return {"service":"Vietsub Pro Realtime API","version":"1.0.0","websocket":"/ws/vietsub","health":"/healthz","model_size":MODEL_SIZE,"device":"cpu"}

@app.post("/api/v1/translate")
async def translate_http(body:TranslateBody,authorization:str|None=Header(default=None)):
    if not authorized(authorization.removeprefix("Bearer ") if authorization else None): raise HTTPException(401,"Unauthorized")
    try: result=await translate(body.text,body.source_lang,body.target_lang)
    except asyncio.TimeoutError: raise HTTPException(504,"Translation timed out")
    return {"status":"success","original":body.text,"translated":result,"source_lang":body.source_lang,"target_lang":body.target_lang}

@app.websocket("/ws/vietsub")
async def websocket_endpoint(ws:WebSocket):
    origin=(ws.headers.get("origin") or "").rstrip("/")
    if ORIGINS and origin not in ORIGINS: await ws.close(code=1008,reason="Origin not allowed"); return
    if not authorized(ws.headers.get("x-internal-token")): await ws.close(code=1008,reason="Unauthorized"); return
    await ws.accept()
    await ws.send_json({"type":"ready","status":"success","version":"1.0.0"})
    try:
        while True:
            raw=await ws.receive_text()
            if len(raw.encode())>MAX_AUDIO_BYTES*2:
                await ws.send_json({"status":"error","error":"message_too_large"}); continue
            try:
                p=__import__("json").loads(raw)
                if not isinstance(p,dict): raise ValueError()
            except Exception:
                await ws.send_json({"status":"error","error":"invalid_json"}); continue
            rid=str(p.get("request_id",""))[:128]; kind=p.get("type","translate_text")
            src=str(p.get("source_lang","auto"))[:16]; tgt=str(p.get("target_lang","vi"))[:16]
            try:
                if kind=="translate_text":
                    text=p.get("text","")
                    if not isinstance(text,str) or not text.strip() or len(text)>MAX_TEXT_CHARS: raise ValueError("invalid_text")
                    translated=await translate(text,src,tgt)
                    await ws.send_json({"type":"translation","request_id":rid,"status":"success","original":text,"translated":translated,"source_lang":src,"target_lang":tgt})
                elif kind=="transcribe_audio":
                    encoded=p.get("audio_base64",""); ext=str(p.get("format","wav"))[:8]
                    if not isinstance(encoded,str) or not encoded or len(encoded)>((MAX_AUDIO_BYTES+2)//3)*4+8: raise ValueError("audio_too_large_or_missing")
                    try: audio=base64.b64decode(encoded,validate=True)
                    except (binascii.Error,ValueError): raise ValueError("invalid_base64")
                    if not audio or len(audio)>MAX_AUDIO_BYTES: raise ValueError("audio_too_large_or_empty")
                    async with inference_lock: result=await asyncio.to_thread(transcribe_sync,audio,ext,src,tgt)
                    await ws.send_json({"type":"transcription","request_id":rid,"status":"success",**result,"source_lang":src,"target_lang":tgt})
                else: await ws.send_json({"status":"error","request_id":rid,"error":"unsupported_type"})
            except asyncio.TimeoutError: await ws.send_json({"status":"error","request_id":rid,"error":"translation_timeout"})
            except ValueError as exc: await ws.send_json({"status":"error","request_id":rid,"error":str(exc)})
            except Exception:
                log.exception("Request failed id=%s type=%s",rid,kind)
                await ws.send_json({"status":"error","request_id":rid,"error":"processing_failed"})
    except WebSocketDisconnect: log.info("Client disconnected")
    except Exception:
        log.exception("WebSocket failure")
        try: await ws.close(code=1011,reason="Internal error")
        except Exception: pass

"""Vietsub Pro realtime WebSocket API.

Development:
    pip install -r requirements-realtime.txt
    python vietsub_realtime_server.py

Optional Colab/ngrok tunnel:
    USE_NGROK=true NGROK_AUTHTOKEN=... python vietsub_realtime_server.py

WebSocket: /ws/vietsub
Health:    /healthz
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
import secrets
import tempfile
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("vietsub-realtime")

app = FastAPI(title="AI Vietsub Realtime WebSocket Server", version="1.0.0")

WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL", "large-v3")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "default")
MAX_AUDIO_BYTES = int(os.getenv("MAX_AUDIO_BYTES", str(12 * 1024 * 1024)))
MAX_TEXT_CHARS = int(os.getenv("MAX_TEXT_CHARS", "5000"))
REQUIRE_WS_AUTH = os.getenv("REQUIRE_WS_AUTH", "false").lower() in {"1", "true", "yes"}
WS_API_TOKEN = os.getenv("WS_API_TOKEN", "")
ALLOWED_ORIGINS = {
    item.strip()
    for item in os.getenv("WS_ALLOWED_ORIGINS", "").split(",")
    if item.strip()
}
ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".mp4", ".webm", ".ogg", ".flac", ".mpeg"}

_whisper_model: Any | None = None
_model_init_lock = threading.Lock()
_inference_lock = threading.Lock()


def get_whisper_model() -> Any:
    """Load Whisper lazily, only when an audio transcription is requested."""
    global _whisper_model
    if _whisper_model is None:
        with _model_init_lock:
            if _whisper_model is None:
                logger.info(
                    "Loading Whisper model=%s device=%s compute_type=%s",
                    WHISPER_MODEL_NAME,
                    WHISPER_DEVICE,
                    WHISPER_COMPUTE_TYPE,
                )
                from faster_whisper import WhisperModel

                _whisper_model = WhisperModel(
                    WHISPER_MODEL_NAME,
                    device=WHISPER_DEVICE,
                    compute_type=WHISPER_COMPUTE_TYPE,
                )
                logger.info("Whisper model loaded")
    return _whisper_model


def _translate_sync(text: str, source_lang: str, target_lang: str) -> dict[str, str | None]:
    """Call third-party translation providers off the event loop."""
    source = (source_lang or "auto").strip()
    target = (target_lang or "vi").strip()
    if not text.strip():
        return {"translated": "", "provider": None, "warning": None}
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"Text exceeds the {MAX_TEXT_CHARS}-character limit")

    # MyMemory expects a language code; use Google directly for auto-detection.
    if source.lower() not in {"auto", "detect", ""}:
        try:
            translated = MyMemoryTranslator(source=source, target=target).translate(text)
            if translated:
                return {"translated": translated, "provider": "mymemory", "warning": None}
        except Exception as exc:
            logger.warning("MyMemory translation failed (%s); trying Google", type(exc).__name__)

    try:
        google_source = "auto" if source.lower() in {"auto", "detect", ""} else source
        translated = GoogleTranslator(source=google_source, target=target).translate(text)
        if translated:
            return {"translated": translated, "provider": "google", "warning": None}
    except Exception as exc:
        logger.warning("Google translation failed (%s)", type(exc).__name__)

    # Do not claim the translation succeeded if both external providers failed.
    return {
        "translated": text,
        "provider": None,
        "warning": "translation_unavailable_original_returned",
    }


def _transcribe_sync(audio_bytes: bytes, extension: str, language: str | None) -> dict[str, Any]:
    """Transcribe uploaded audio using faster-whisper in a worker thread."""
    if not audio_bytes:
        raise ValueError("Audio payload is empty")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise ValueError(f"Audio exceeds the {MAX_AUDIO_BYTES}-byte limit")

    suffix = extension.lower()
    if suffix not in ALLOWED_AUDIO_EXTENSIONS:
        suffix = ".wav"

    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="vietsub-", suffix=suffix, delete=False) as temp_file:
            temp_file.write(audio_bytes)
            temp_path = temp_file.name

        model = get_whisper_model()
        with _inference_lock:
            segments_iter, info = model.transcribe(
                temp_path,
                language=language,
                beam_size=5,
                vad_filter=True,
            )
            segments: list[dict[str, Any]] = []
            transcript_parts: list[str] = []
            for segment in segments_iter:
                segment_text = (segment.text or "").strip()
                if segment_text:
                    transcript_parts.append(segment_text)
                    segments.append({
                        "start": round(float(segment.start), 3),
                        "end": round(float(segment.end), 3),
                        "text": segment_text,
                    })
                if len(segments) >= 5000:
                    logger.warning("Transcription output reached 5000 segment cap")
                    break

        return {
            "text": " ".join(transcript_parts).strip(),
            "detected_language": getattr(info, "language", None),
            "language_probability": round(float(getattr(info, "language_probability", 0.0)), 4),
            "segments": segments,
        }
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove temporary audio file")


async def translate_text(text: str, source_lang: str, target_lang: str) -> dict[str, str | None]:
    return await run_in_threadpool(_translate_sync, text, source_lang, target_lang)


async def authenticate_websocket(websocket: WebSocket) -> bool:
    """When enabled, require an initial JSON auth message: {type:'auth', token:'...'}"""
    if not REQUIRE_WS_AUTH:
        return True
    if not WS_API_TOKEN:
        logger.error("REQUIRE_WS_AUTH=true but WS_API_TOKEN is missing")
        await websocket.send_json({"status": "error", "code": "server_auth_not_configured"})
        await websocket.close(code=1011)
        return False
    try:
        first_message = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        payload = json.loads(first_message)
        supplied_token = payload.get("token", "") if isinstance(payload, dict) else ""
    except (asyncio.TimeoutError, json.JSONDecodeError, WebSocketDisconnect):
        await websocket.close(code=1008, reason="Authentication required")
        return False
    if not secrets.compare_digest(str(supplied_token), WS_API_TOKEN):
        await websocket.send_json({"status": "error", "code": "unauthorized"})
        await websocket.close(code=1008, reason="Unauthorized")
        return False
    await websocket.send_json({"status": "success", "type": "authenticated"})
    return True


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "AI Vietsub Realtime WebSocket Server"}


@app.get("/api/v1/meta")
async def api_meta() -> dict[str, Any]:
    return {
        "service": "AI Vietsub Realtime WebSocket Server",
        "version": app.version,
        "websocket": "/ws/vietsub",
        "health": "/healthz",
        "operations": ["translate_text", "transcribe_audio"],
    }


@app.websocket("/ws/vietsub")
async def websocket_vietsub(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    if ALLOWED_ORIGINS and (not origin or origin not in ALLOWED_ORIGINS):
        await websocket.close(code=1008, reason="Origin not allowed")
        return

    await websocket.accept()
    logger.info("WebSocket client connected")
    try:
        if not await authenticate_websocket(websocket):
            return

        while True:
            raw_message = await websocket.receive_text()
            try:
                payload = json.loads(raw_message)
            except json.JSONDecodeError:
                await websocket.send_json({"status": "error", "code": "invalid_json"})
                continue

            if not isinstance(payload, dict):
                await websocket.send_json({"status": "error", "code": "json_object_required"})
                continue

            request_id = payload.get("request_id")
            operation = payload.get("type") or ("translate_text" if "text" in payload else "")

            try:
                if operation == "translate_text":
                    source_text = payload.get("text", "")
                    if not isinstance(source_text, str):
                        raise ValueError("text must be a string")
                    if len(source_text) > MAX_TEXT_CHARS:
                        raise ValueError(f"Text exceeds the {MAX_TEXT_CHARS}-character limit")
                    source_lang = str(payload.get("source_lang", "auto"))
                    target_lang = str(payload.get("target_lang", "vi"))
                    result = await translate_text(source_text, source_lang, target_lang)
                    await websocket.send_json({
                        "status": "success" if not result["warning"] else "partial",
                        "type": "translation_result",
                        "request_id": request_id,
                        "original": source_text,
                        "translated": result["translated"],
                        "source_lang": source_lang,
                        "target_lang": target_lang,
                        "provider": result["provider"],
                        "warning": result["warning"],
                    })

                elif operation == "transcribe_audio":
                    encoded_audio = payload.get("audio_base64", "")
                    if not isinstance(encoded_audio, str) or not encoded_audio:
                        raise ValueError("audio_base64 is required")
                    # Reject obviously oversized base64 before decoding it.
                    max_encoded_length = ((MAX_AUDIO_BYTES + 2) // 3) * 4 + 8
                    if len(encoded_audio) > max_encoded_length:
                        raise ValueError(f"Audio exceeds the {MAX_AUDIO_BYTES}-byte limit")
                    try:
                        audio_bytes = base64.b64decode(encoded_audio, validate=True)
                    except (binascii.Error, ValueError) as exc:
                        raise ValueError("audio_base64 is not valid base64") from exc
                    if len(audio_bytes) > MAX_AUDIO_BYTES:
                        raise ValueError(f"Audio exceeds the {MAX_AUDIO_BYTES}-byte limit")

                    filename = str(payload.get("filename", "audio.wav"))
                    extension = Path(filename).suffix.lower()
                    requested_source = str(payload.get("source_lang", "auto"))
                    whisper_language = None if requested_source.lower() in {"auto", "detect", ""} else requested_source
                    transcription = await run_in_threadpool(
                        _transcribe_sync, audio_bytes, extension, whisper_language
                    )
                    target_lang = str(payload.get("target_lang", "vi"))
                    translated = await translate_text(
                        transcription["text"],
                        str(transcription["detected_language"] or requested_source),
                        target_lang,
                    ) if transcription["text"] else {
                        "translated": "", "provider": None, "warning": None
                    }
                    await websocket.send_json({
                        "status": "success" if not translated["warning"] else "partial",
                        "type": "transcription_result",
                        "request_id": request_id,
                        "original": transcription["text"],
                        "translated": translated["translated"],
                        "detected_lang": transcription["detected_language"],
                        "language_probability": transcription["language_probability"],
                        "target_lang": target_lang,
                        "translation_provider": translated["provider"],
                        "warning": translated["warning"],
                        "segments": transcription["segments"],
                    })
                else:
                    await websocket.send_json({
                        "status": "error",
                        "request_id": request_id,
                        "code": "unsupported_operation",
                        "supported_types": ["translate_text", "transcribe_audio"],
                    })
            except ValueError as exc:
                await websocket.send_json({
                    "status": "error", "request_id": request_id,
                    "code": "invalid_request", "message": str(exc),
                })
            except Exception:
                logger.exception("Request failed; request_id=%s operation=%s", request_id, operation)
                await websocket.send_json({
                    "status": "error", "request_id": request_id,
                    "code": "processing_failed",
                    "message": "The request could not be processed. Check server logs.",
                })

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception:
        logger.exception("Unexpected WebSocket failure")
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


def main() -> None:
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    if os.getenv("USE_NGROK", "false").lower() in {"1", "true", "yes"}:
        auth_token = os.getenv("NGROK_AUTHTOKEN", "").strip()
        if not auth_token:
            raise RuntimeError("USE_NGROK=true requires NGROK_AUTHTOKEN in the environment")
        from pyngrok import ngrok

        ngrok.set_auth_token(auth_token)
        tunnel = ngrok.connect(str(port), "http")
        public_url = tunnel.public_url
        websocket_scheme = "wss" if public_url.startswith("https://") else "ws"
        base_url = public_url.replace("https://", "").replace("http://", "")
        logger.info("Public HTTP URL: %s", public_url)
        logger.info("Public WebSocket URL: %s://%s/ws/vietsub", websocket_scheme, base_url)

    logger.info("Starting server on %s:%s", host, port)
    ws_max_size = int(os.getenv("WS_MAX_SIZE", str(20 * 1024 * 1024)))
    uvicorn.run(
        app, host=host, port=port,
        ws_max_size=ws_max_size,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()

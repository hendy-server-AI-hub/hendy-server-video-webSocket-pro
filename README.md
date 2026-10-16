# Vietsub Realtime WebSocket Server

FastAPI WebSocket service for text translation and audio transcription + Vietnamese translation. Whisper loads lazily only for audio requests, and translation/transcription work runs off the ASGI event loop.

## Install and run

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-realtime.txt
python vietsub_realtime_server.py
```

Endpoints:
- `GET /healthz`
- `GET /api/v1/meta`
- `WS /ws/vietsub`

## WebSocket request: text translation

```json
{
  "type": "translate_text",
  "request_id": "req-001",
  "text": "Hello, how are you?",
  "source_lang": "auto",
  "target_lang": "vi"
}
```

For compatibility, a payload containing `text` without `type` is also treated as `translate_text`.

## WebSocket request: audio transcription + translation

The client sends audio as base64-encoded bytes. This is convenient for a prototype client but adds about 33% overhead; for large media, use a separate authenticated upload endpoint or object storage instead.

```json
{
  "type": "transcribe_audio",
  "request_id": "req-002",
  "filename": "clip.wav",
  "audio_base64": "<BASE64_AUDIO_BYTES>",
  "source_lang": "auto",
  "target_lang": "vi"
}
```

The response includes `original`, `translated`, detected language, and timestamped segments.

## Optional ngrok tunnel (development/Colab only)

Do not put tokens in source code or commit them to Git. Set them as environment variables:

```bash
# Linux/macOS
export USE_NGROK=true
export NGROK_AUTHTOKEN="your-token"
python vietsub_realtime_server.py
```

On Windows PowerShell:

```powershell
$env:USE_NGROK="true"
$env:NGROK_AUTHTOKEN="your-token"
python .\vietsub_realtime_server.py
```

## Optional WebSocket auth and origin allowlist

Set `REQUIRE_WS_AUTH=true` and `WS_API_TOKEN` to require an initial JSON message:

```json
{"type":"auth","token":"your-shared-token"}
```

Set `WS_ALLOWED_ORIGINS` to a comma-separated list of exact browser origins, for example:

```text
WS_ALLOWED_ORIGINS=https://studio.example.com,https://admin.example.com
```

When authentication is enabled, configure the client to send the auth message immediately after connecting, before its first work request. Do not expose `WS_API_TOKEN` in public frontend code: browser clients should get short-lived credentials from an authenticated backend.

## Useful environment variables

- `PORT` (default `8000`)
- `WHISPER_MODEL` (default `large-v3`; model loads only when audio is requested)
- `WHISPER_DEVICE` (default `auto`)
- `WHISPER_COMPUTE_TYPE` (default `default`)
- `MAX_AUDIO_BYTES` (default 12 MiB)
- `MAX_TEXT_CHARS` (default 5000)
- `USE_NGROK` / `NGROK_AUTHTOKEN`
- `REQUIRE_WS_AUTH` / `WS_API_TOKEN` / `WS_ALLOWED_ORIGINS`

## Production notes

- Use HTTPS/WSS behind a managed ingress or reverse proxy; ngrok is for development, not a durable production endpoint.
- Configure authentication, origin restrictions, rate limits, per-user quotas, request timeouts, and observability before exposing the endpoint publicly.
- External translation providers can rate-limit or change availability. This service reports `status: partial` and a warning when both providers fail instead of claiming translation succeeded.
- `large-v3` can require substantial memory/compute. Choose a smaller model or a GPU-capable host if needed.
- This service is a single-process baseline. For horizontal scaling, use a job queue for long audio tasks and separate workers with their own model/resource limits.

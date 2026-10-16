# Vietsub Pro Realtime — Cloudflare + GitHub

Starter source for a Cloudflare Worker + Durable Object WebSocket gateway and a CPU Python/FastAPI/Faster-Whisper container. It has not been deployed to your account; validate current Cloudflare Containers support and Wrangler configuration before production.

## Flow
Browser WSS → Worker (token + Origin check) → Durable Object → Python Container (FastAPI `/ws/vietsub`).

## Local run
Python 3.11+, Docker, Node 22+:
```bash
cd apps/vietsub-realtime
python -m venv .venv
# Windows: .venv\\Scripts\\activate
source .venv/bin/activate
pip install -r requirements.txt
export INTERNAL_API_TOKEN='use-a-long-random-secret'
export MODEL_SIZE=small
uvicorn main:app --host 0.0.0.0 --port 8000
```
`GET /healthz` and `GET /api/v1/meta` are health/metadata endpoints. `large-v3` is resource-heavy on CPU; default `small` is for smoke testing. Benchmark before production.

## Deploy
1. Copy this folder into your GitHub repository (or merge folders into your monorepo).
2. Set a unique Worker name in `apps/api/wrangler.jsonc`.
3. Create a Cloudflare Workers Paid account/enable Containers if required.
4. Install and authenticate: `npm install`, `npx wrangler login`.
5. Add runtime secrets:
```bash
npx wrangler secret put VIETSUB_WS_TOKEN --config apps/api/wrangler.jsonc
npx wrangler secret put VIETSUB_INTERNAL_TOKEN --config apps/api/wrangler.jsonc
```
Use separate random secrets. Configure the same internal token in the Python container as `INTERNAL_API_TOKEN` using the supported runtime secret mechanism for the selected Container deployment. Never commit secrets.
6. Set `ALLOWED_ORIGIN` to the exact Studio URL in `wrangler.jsonc`.
7. Deploy with `npx wrangler deploy --config apps/api/wrangler.jsonc`.
8. For GitHub Actions add repository secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`. The token needs the minimum Workers/Containers deployment permissions. Push to `main`.

Cloudflare Workers Builds Git integration is an alternative to GitHub Actions. Avoid two competing production deploy pipelines.

## WebSocket messages
Text:
```json
{"type":"translate_text","request_id":"r1","text":"Hello","source_lang":"auto","target_lang":"vi"}
```
Audio (base64; limited by `MAX_AUDIO_BYTES`):
```json
{"type":"transcribe_audio","request_id":"r2","audio_base64":"...","source_lang":"auto","target_lang":"vi","format":"wav"}
```
For long videos, upload to R2 and enqueue a background job rather than sending large base64 frames through WebSocket.

## Variables
Python: `INTERNAL_API_TOKEN` (required), `MODEL_SIZE` (small default), `COMPUTE_TYPE` (int8), `MAX_AUDIO_BYTES` (8 MiB), `MAX_TEXT_CHARS` (5000), `ALLOWED_ORIGINS`, `TRANSLATION_TIMEOUT_SECONDS`.
Worker secrets: `VIETSUB_WS_TOKEN`, `VIETSUB_INTERNAL_TOKEN`. Plain variable: `ALLOWED_ORIGIN`.

## Production checklist
- WSS only; rotate any exposed Ngrok token and never commit credentials.
- Configure WAF/rate limits and monitor container memory/CPU.
- Add short-lived WebSocket tickets instead of long-lived query tokens for browser authentication.
- Add signed R2 uploads, durable job queue, retention policy, and load tests before accepting large media.
- Health check reports process liveness; it does not guarantee Whisper model is downloaded or warmed.

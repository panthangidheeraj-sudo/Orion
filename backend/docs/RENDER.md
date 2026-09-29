# Deploying Orion on Render (public API + private vision service)

```
browser ──HTTPS──> orion-api (web)  ──private HTTP + X-Orion-Internal-Key──> orion-vision (pserv)
                     │  Firebase (browser-side auth/Firestore sync, unchanged)
                     └─ hosted Groq reasoning (server-side key)
```

`render.yaml` at the repo root defines both services in one region (`oregon`) in
one workspace. That is required for Render private networking, and the two
`region:` lines must stay equal.

## Services

| Service | Type | Plan | Port | Start command |
|---|---|---|---|---|
| `orion-api` | web (public HTTPS) | `0.5c-512mb` (raise to `1c-2g` if it runs out of memory) | 10000 | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| `orion-vision` | pserv (no public URL) | `1c-2g` | 10000 | `uvicorn app.vision_service:app --host 0.0.0.0 --port $PORT` |

Private services need a paid plan. There is no `orion-model` service.

## Environment variables

| Variable | Service | Value |
|---|---|---|
| `VF_INTERNAL_KEY` | both | generated once by Render (`orion-internal` group); never committed |
| `VF_VISION_URL` | api | `fromService` hostport, e.g. `orion-vision:10000` |
| `GROQ_API_KEY` | api | `sync:false`, entered in the dashboard |
| `VF_ACCESS_TOKEN` | api | `sync:false`, the browser access key |
| `VF_CORS_ORIGINS` | api | `sync:false`, JSON list of the frontend origin(s) |
| `VF_REASONING_PROVIDER` | api | `hosted-groq` |
| `VF_HOSTED_LLM_MODEL` | api | `qwen/qwen3.8-27b` |
| `VF_EPHEMERAL_STORAGE` | api | `true` |
| `VF_HOST`, `VF_TRUST_PROXY_HEADERS`, `PORT`, `PYTHON_VERSION` | api | see `render.yaml` |
| `VF_ONNX_EXECUTION_PROVIDERS` | vision | `["CPUExecutionProvider"]` |
| `VF_INTERNAL_MAX_CONCURRENCY` | vision | `2` |
| `VF_INTERNAL_MAX_IMAGE_BYTES` | vision | optional, default 20 MB |
| `VF_VISION_TIMEOUT_S`, `VF_VISION_STATUS_TTL_S` | api | optional, defaults 30 / 10 |

## Internal API (orion-vision)

All routes need `X-Orion-Internal-Key: $VF_INTERNAL_KEY` (constant-time compare),
except `GET /healthz`, which returns only `{"ok": true}`. The service refuses to
start without the key. Docs/OpenAPI are disabled.

- `GET /internal/status` returns the real health of `detector`, `classifier`, `segmenter`, `tracker`, `ocr`.
- `POST /internal/detect`, `/classify`, `/segment`, `/track`, `/ocr` take multipart `image` plus optional JSON `meta` (`bbox`, `target`, or tracker `state`) and return `{role, provider, model_id, accelerator, npu:false, result}`. A role that is not READY returns 503 `MODEL_UNAVAILABLE`.

## Honesty rules

- The API marks a vision role READY only when the vision service's own
  `/internal/status` says READY (cached at most 10 s; a failed call drops the cache immediately).
- If the service is unreachable, rejects the key, or is not configured, those roles
  report `unavailable` with the real reason, tools return their degraded fallbacks,
  and the API, Firebase sync and hosted Groq keep working. The Live screen shows a
  role as idle/running only when `/api/models/status` lists it as ready.
- Remote roles are `hosted: true` and `npu: false`. Nothing on Render claims
  NPU/Qualcomm acceleration.
- `tracker` in `auto` mode stays the free in-process classical tracker;
  set `VF_TRACKER_PROVIDER=remote-vision` to use the service's tracker.

## Models

No model weights are in the repo or installed by `requirements-vision.txt`. With no
assets present, only the classical tracker is READY on the vision service; detector,
classifier, segmenter and OCR report `unavailable` until assets exist under
`VF_MODEL_DIR` (and, for OCR, the package the adapter needs). Hosted Groq remains the
reasoning and image-reading path for the demo.

The Snapdragon GenieX/QAIRT path and the on-device SQLite data are untouched and not
part of this deployment.

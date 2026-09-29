"""orion-vision — the private vision service (Render ``pserv``).

Run:  uvicorn app.vision_service:app --host 0.0.0.0 --port $PORT

What it is: the detector, classifier, segmenter, OCR and tracker adapters
behind a small internal HTTP API. It takes image *bytes* (the API's disk is not
shared), runs the same adapter classes the on-device build uses, and reports
their real health. It owns no user data, no database, no Firebase and no
reasoning model.

What it is not:
- It is not public. Deploy it as a private service; it has no public URL.
- It is not trusted just because the network is private. Every route except the
  bare liveness probe ``/healthz`` requires ``X-Orion-Internal-Key`` equal to
  ``VF_INTERNAL_KEY``, compared in constant time. It refuses to start without
  the key.
- It never claims acceleration it does not have. It runs on Render CPU; the
  adapters report whatever provider the runtime actually applied.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import tempfile
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from app.config import settings
from app.errors import ModelUnavailable, PayloadTooLarge, UnsupportedMedia, ValidationFailed, VFError
from app.logging_setup import configure_logging, get_logger

# This process must never call another vision service (no loops), whatever
# environment it was started with.
settings.vision_url = ""

from app.models import base  # noqa: E402
from app.models.base import ImageRef  # noqa: E402
from app.models.registry import registry  # noqa: E402

log = get_logger(__name__)

KEY_HEADER = "x-orion-internal-key"
ROLES = ("detector", "classifier", "segmenter", "tracker", "ocr")
_FORMATS = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"),
            "WEBP": ("webp", "image/webp")}

_gate: Optional[asyncio.Semaphore] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _gate
    configure_logging()
    if not settings.internal_key:
        # Fail closed: an internal service with no key would be open to anything
        # that can reach it on the private network.
        raise RuntimeError("VF_INTERNAL_KEY is not set; orion-vision refuses to start "
                           "without service-to-service authentication.")
    _gate = asyncio.Semaphore(max(1, settings.internal_max_concurrency))
    log.info("orion-vision up; roles are loaded lazily on first status or call")
    yield


app = FastAPI(title="orion-vision", version="1.0.0", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


def _deny(status: int, code: str, reason: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "reason": reason},
                        headers={"X-Content-Type-Options": "nosniff"})


@app.middleware("http")
async def internal_auth(request: Request, call_next):
    # The one unauthenticated route says nothing about models or configuration.
    if request.url.path == "/healthz" and request.method in ("GET", "HEAD"):
        return await call_next(request)
    expected = settings.internal_key
    presented = request.headers.get(KEY_HEADER, "").strip()
    if not expected or not hmac.compare_digest(presented.encode(), expected.encode()):
        return _deny(401, "UNAUTHORIZED", "a valid internal key is required")
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > settings.internal_max_image_bytes + (1 << 20):
        return _deny(413, "PAYLOAD_TOO_LARGE", "image is too large")
    return await call_next(request)


@app.exception_handler(VFError)
async def vf_error(request: Request, exc: VFError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content=exc.to_dict())


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={
        "error": "INTERNAL_ERROR", "reason": f"{type(exc).__name__} while handling the request"})


@app.get("/healthz")
async def healthz() -> Dict[str, bool]:
    return {"ok": True}


def _role_status(role: str) -> Dict[str, Any]:
    adapter = registry.get(role)
    h = adapter.health()
    reason = h.reason
    if h.status != base.READY:
        # The placeholder's reason is generic; the candidate that was tried knows why.
        tried = next((c.get("reason") for c in registry._attempts.get(role, [])
                      if c.get("reason")), None)
        reason = tried or reason
    return {"status": h.status, "provider": h.provider, "model_id": h.model_id,
            "runtime": h.runtime, "accelerator": h.accelerator, "npu": bool(h.npu),
            "synthetic": h.synthetic, "load_ms": h.load_ms, "reason": reason}


@app.get("/internal/status")
def status() -> Dict[str, Any]:
    roles = {r: _role_status(r) for r in ROLES}
    return {"service": "orion-vision", "version": app.version,
            "ready": [r for r, v in roles.items() if v["status"] == base.READY],
            "roles": roles}


async def _read_image(image: UploadFile) -> bytes:
    limit = settings.internal_max_image_bytes
    buf = bytearray()
    while True:
        chunk = await image.read(1 << 20)
        if not chunk:
            break
        buf += chunk
        if len(buf) > limit:
            raise PayloadTooLarge(f"image is larger than {limit // 1048576} MB")
    if not buf:
        raise ValidationFailed("the image part is empty")
    return bytes(buf)


def _meta(raw: str) -> Dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except ValueError:
        raise ValidationFailed("meta must be a JSON object")
    if not isinstance(value, dict):
        raise ValidationFailed("meta must be a JSON object")
    return value


def _stage(data: bytes, image_id: str) -> ImageRef:
    """Validate the bytes really are an image and give adapters a contained temp path."""
    from PIL import Image

    try:
        with Image.open(__import__("io").BytesIO(data)) as im:
            fmt, (w, h) = im.format, im.size
            im.verify()
    except Exception:
        raise UnsupportedMedia("the upload is not a decodable image")
    if fmt not in _FORMATS:
        raise UnsupportedMedia(f"unsupported image format {fmt}")
    ext, mime = _FORMATS[fmt]
    fd, path = tempfile.mkstemp(suffix="." + ext, prefix="vf_remote_")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return ImageRef(id=image_id[:64] or "remote", path=path, width=w, height=h,
                    mime_type=mime, source="remote")


async def _run(role: str, image: UploadFile, meta_raw: str, fn) -> JSONResponse:
    meta = _meta(meta_raw)
    data = await _read_image(image)
    adapter = registry.get(role)
    # The role must be READY *now*: a placeholder never answers, and nothing
    # substitutes another model.
    if not adapter.is_ready():
        raise ModelUnavailable(_role_status(role)["reason"] or "role is not ready",
                               model=adapter.model_id, role=role, provider=adapter.provider)
    ref = _stage(data, image.filename or "remote")
    try:
        assert _gate is not None
        async with _gate:
            result = await fn(adapter, ref, meta)
    finally:
        try:
            os.unlink(ref.path)
        except OSError:
            pass
    h = adapter.health()
    return JSONResponse({"role": role, "provider": h.provider, "model_id": h.model_id,
                         "runtime": h.runtime, "accelerator": h.accelerator, "npu": bool(h.npu),
                         "synthetic": h.synthetic, "result": result})


def _bbox(meta: Dict[str, Any]):
    box = meta.get("bbox")
    if box is None:
        return None
    if (not isinstance(box, list) or len(box) != 4
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in box)):
        raise ValidationFailed("bbox must be [x1,y1,x2,y2] numbers")
    return [float(v) for v in box]


@app.post("/internal/detect")
async def detect(image: UploadFile = File(...), meta: str = Form("{}")):
    return await _run("detector", image, meta, lambda a, r, m: a.detect(r))


@app.post("/internal/classify")
async def classify(image: UploadFile = File(...), meta: str = Form("{}")):
    return await _run("classifier", image, meta, lambda a, r, m: a.classify(r, _bbox(m)))


@app.post("/internal/segment")
async def segment(image: UploadFile = File(...), meta: str = Form("{}")):
    def call(a, r, m):
        target = m.get("target")
        if target is not None and not isinstance(target, str):
            raise ValidationFailed("target must be a string")
        return a.segment(r, target)
    return await _run("segmenter", image, meta, call)


@app.post("/internal/track")
async def track(image: UploadFile = File(...), meta: str = Form("{}")):
    def call(a, r, m):
        state = m.get("state")
        if state is not None and not isinstance(state, dict):
            raise ValidationFailed("state must be an object")
        return a.track(r, state)
    return await _run("tracker", image, meta, call)


@app.post("/internal/ocr")
async def ocr(image: UploadFile = File(...), meta: str = Form("{}")):
    return await _run("ocr", image, meta, lambda a, r, m: a.extract(r))

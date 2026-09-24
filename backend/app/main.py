"""VisionField Copilot backend.

A local FastAPI service.  The front-end talks to it over http://127.0.0.1 and
owns none of the orchestration: §20 and §28 make the backend "the single owner
of AI orchestration, memory, tool execution, local model inference and
document/knowledge processing."

Run it:

    python -m app.main
    # or
    uvicorn app.main:app --host 127.0.0.1 --port 8756
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import chat, documents, jobs, live, photos, system, voice
from app.config import settings
from app.errors import VFError
from app.logging_setup import configure_logging, get_logger
from app.memory.sqlite import init_db
from app.models.registry import registry as models
from app.util import ms

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings.ensure_dirs()
    init_db()
    # Imported for the side effect of registering every tool with the registry.
    import app.tools  # noqa: F401
    from app.memory import memory_service

    memory_service.ensure_user()

    status = models.status()["summary"]
    log.info("models ready=%s unavailable=%s npu=%s",
             status["ready"], status["unavailable"],
             status["npu_accelerated"] or "none")
    if status["synthetic"]:
        log.warning("roles running deterministic stand-ins: %s — see MODEL_STATUS.md",
                    ", ".join(status["synthetic"]))
    log.info("listening on http://%s:%d", settings.host, settings.port)
    yield
    log.info("shutting down")


app = FastAPI(
    title="VisionField Copilot",
    description="Local-first multimodal field-technician agent. "
                "The VLM is the brain; everything else is a sense, memory store or tool.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
    max_age=600,
)


@app.middleware("http")
async def timing(request: Request, call_next):
    start = ms()
    response = await call_next(request)
    response.headers["X-Response-Time-ms"] = f"{ms() - start:.1f}"
    return response


@app.exception_handler(VFError)
async def vf_error_handler(request: Request, exc: VFError) -> JSONResponse:
    """Every failure leaves as the §25 envelope, never as a stack trace."""
    log.info("%s on %s: %s", exc.code, request.url.path, exc.reason)
    return JSONResponse(status_code=exc.http_status, content=exc.to_dict())


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={
        "error": "VALIDATION_FAILED",
        "reason": "the request body did not match the expected shape",
        "details": [
            {"loc": [str(p) for p in e.get("loc", [])], "msg": e.get("msg")}
            for e in exc.errors()[:8]
        ],
    })


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    # The message is deliberately generic: §24 forbids leaking internals.
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={
        "error": "INTERNAL_ERROR",
        "reason": f"{type(exc).__name__} while handling the request",
    })


for _router in (chat.router, photos.router, live.router, documents.router,
                jobs.router, voice.router, system.router):
    app.include_router(_router)


@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "app": "VisionField Copilot backend",
        "version": "1.0.0",
        "docs": "/docs",
        "status": "/api/system/status",
        "models": "/api/models/status",
        "principle": "The VLM is the brain. Everything else is a sense, memory store, or tool.",
    }


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port,
                log_level=settings.log_level.lower(), reload=False)


if __name__ == "__main__":
    main()

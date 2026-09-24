"""Voice endpoints (§17): /api/voice/transcribe, /api/voice/synthesize.

Local only.  §17: "Do not require cloud speech services for the core path."
When no local model is available the response says so and the front-end keeps
using its own recogniser or plain typing — §25's graceful degradation.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse

from app.api._media import read_upload
from app.errors import ModelUnavailable, NotFound
from app.config import settings
from app.logging_setup import get_logger
from app.models.registry import registry as models
from app.schemas.tools import SynthesizeRequest
from app.util import contained_path, timed

log = get_logger(__name__)
router = APIRouter(prefix="/api/voice", tags=["voice"])

MAX_AUDIO_BYTES = 30 * 1024 * 1024


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...)) -> Dict[str, Any]:
    data = await read_upload(file, limit=MAX_AUDIO_BYTES)
    stt = models.stt()
    if not stt.is_ready():
        h = stt.health()
        return {"text": "", "degraded": True, "model": h.model_id,
                "reason": h.reason or "no local speech-to-text model available",
                "fallback": "use the browser's own speech recognition, or type the question"}
    with timed() as t:
        try:
            result = await stt.transcribe(data, file.content_type or "audio/wav")
        except ModelUnavailable as exc:
            return {"text": "", "degraded": True, **exc.to_dict()}
    return {**result, "degraded": False, "duration_ms": t["ms"],
            "accelerator": stt.health().accelerator, "npu": stt.health().npu}


@router.post("/synthesize")
async def synthesize(req: SynthesizeRequest) -> Dict[str, Any]:
    tts = models.tts()
    if not tts.is_ready():
        h = tts.health()
        # §25: TTS unavailable -> the text response still stands.
        return {"audio_id": None, "degraded": True, "model": h.model_id,
                "reason": h.reason or "no local text-to-speech model available",
                "text": req.text,
                "fallback": "the browser's speech synthesis, or read the text response"}
    with timed() as t:
        try:
            result = await tts.synthesize(req.text, req.voice)
        except ModelUnavailable as exc:
            return {"audio_id": None, "degraded": True, "text": req.text, **exc.to_dict()}
    result.pop("audio_path", None)
    return {**result, "degraded": False, "duration_ms": t["ms"]}


@router.get("/audio/{audio_id}")
async def get_audio(audio_id: str) -> FileResponse:
    path = contained_path(settings.audio_dir, f"{audio_id}.wav")
    if not path.exists():
        raise NotFound("no such audio clip", audio_id=audio_id)
    return FileResponse(path, media_type="audio/wav")

"""Photo mode (§7): /api/photo/analyze, /api/photo/analyze-multiple.

    Photo(s) -> detection -> classification -> OCR -> segmentation
             -> visual evidence package -> document/memory retrieval
             -> main VLM -> diagnosis

Multiple photos belong to one inspection context, and only the useful results
are carried into reasoning rather than every image repeatedly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, UploadFile

from app.agent.orchestrator import orchestrator
from app.agent.tool_registry import registry as tool_registry
from app.api._media import read_upload, store_image
from app.errors import ValidationFailed
from app.logging_setup import get_logger
from app.memory import memory_service as M

log = get_logger(__name__)
router = APIRouter(prefix="/api/photo", tags=["photo"])

DEFAULT_QUESTION = ("Inspect this image. Say what you can actually see, what it suggests, "
                    "and what I should check next.")


async def _analyze(images: List[bytes], question: Optional[str], conversation_id: Optional[str],
                   job_id: Optional[str], inspection_id: Optional[str],
                   web: bool) -> Dict[str, Any]:
    if not images:
        raise ValidationFailed("at least one image is required")

    conversation = M.ensure_conversation(conversation_id,
                                         title=(question or "Photo inspection")[:60])
    stored = [store_image(data, source="photo", conversation_id=conversation["id"],
                          inspection_id=inspection_id) for data in images]
    image_ids = [s["image_id"] for s in stored]

    result = await orchestrator.ask(
        question or DEFAULT_QUESTION,
        conversation_id=conversation["id"], image_ids=image_ids, job_id=job_id,
        inspection_id=inspection_id, mode="normal", web=web)

    return {**result, "images": stored, "image_ids": image_ids}


@router.post("/analyze")
async def analyze(file: UploadFile = File(...),
                  question: Optional[str] = Form(None),
                  conversation_id: Optional[str] = Form(None),
                  job_id: Optional[str] = Form(None),
                  inspection_id: Optional[str] = Form(None),
                  web: bool = Form(False)) -> Dict[str, Any]:
    data = await read_upload(file)
    return await _analyze([data], question, conversation_id, job_id, inspection_id, web)


@router.post("/analyze-multiple")
async def analyze_multiple(files: List[UploadFile] = File(...),
                           question: Optional[str] = Form(None),
                           conversation_id: Optional[str] = Form(None),
                           job_id: Optional[str] = Form(None),
                           inspection_id: Optional[str] = Form(None),
                           web: bool = Form(False)) -> Dict[str, Any]:
    if len(files) > 8:
        raise ValidationFailed("at most 8 photos belong to one inspection turn",
                               received=len(files))
    datas = [await read_upload(f) for f in files]
    return await _analyze(datas, question, conversation_id, job_id, inspection_id, web)


@router.post("/upload")
async def upload_only(file: UploadFile = File(...),
                      conversation_id: Optional[str] = Form(None),
                      inspection_id: Optional[str] = Form(None)) -> Dict[str, Any]:
    """Store a photo without reasoning about it yet — used when the technician
    attaches images before typing the question."""
    data = await read_upload(file)
    return store_image(data, source="photo", conversation_id=conversation_id,
                       inspection_id=inspection_id)


@router.post("/inspect")
async def inspect_only(image_id: str = Form(...)) -> Dict[str, Any]:
    """Run the visual senses on a stored photo and return the raw evidence."""
    ctx = {"image_ids": [image_id]}
    detect = await tool_registry.call("vision_detect", {"image_id": image_id}, context=ctx)
    ocr = await tool_registry.call("ocr_extract", {"image_id": image_id}, context=ctx)
    return {"image_id": image_id, "detect": detect, "ocr": ocr}

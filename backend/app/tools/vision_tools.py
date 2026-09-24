"""Vision tools (§15).

Images are addressed by ``image_id``, never by path.  The resolver looks the
id up in the ``images`` table and re-checks that the stored path is still
inside the data directory, so a tool argument cannot aim a model at an
arbitrary file (§15, §24).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agent.tool_registry import registry as tools
from app.config import settings
from app.errors import NotFound, ToolError
from app.logging_setup import get_logger
from app.memory import sqlite as db
from app.models._imaging import image_stats
from app.models.base import ImageRef
from app.models.registry import registry as models

log = get_logger(__name__)


def resolve_image(image_id: str) -> ImageRef:
    row = db.query_one("SELECT * FROM images WHERE id = ?", (image_id,))
    if not row:
        raise NotFound("no such image", image_id=image_id)
    path = Path(row["path"])
    data_root = settings.data_dir.resolve()
    if data_root not in path.resolve().parents:
        raise ToolError("stored image lies outside the data directory", tool="resolve_image")
    if not path.exists():
        raise NotFound("image is missing from disk", image_id=image_id)
    return ImageRef(id=row["id"], path=str(path), width=row["width"] or 0,
                    height=row["height"] or 0, mime_type=row["mime_type"] or "image/jpeg",
                    source=row["source"] or "photo")


def _pick(image_id: Optional[str], context: Dict[str, Any]) -> ImageRef:
    if image_id:
        return resolve_image(image_id)
    ids = context.get("image_ids") or []
    if not ids:
        raise ToolError("no image is attached to this turn", tool="vision")
    return resolve_image(ids[-1])


IMAGE_ARG = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "image_id": {"type": "string", "maxLength": 64,
                     "description": "Image to inspect. Defaults to the newest image in this turn."},
    },
}


@tools.tool(
    "vision_detect",
    "Detect objects and components in an attached image. Returns labels, "
    "confidences and pixel bounding boxes.",
    IMAGE_ARG, category="vision", needs_roles=["detector"])
async def vision_detect(image_id: Optional[str] = None, context: Dict[str, Any] = None):
    ref = _pick(image_id, context or {})
    detector = models.detector()
    stats = image_stats(ref)
    if not detector.is_ready():
        h = detector.health()
        # §25: detector unavailable -> the VLM can still inspect the image.
        return {"detections": [], "image": {**stats, "image_id": ref.id},
                "degraded": True, "model": h.model_id,
                "reason": h.reason or "no detector available",
                "fallback": "the reasoning model inspects the image directly"}
    detections = await detector.detect(ref)
    return {"detections": detections, "count": len(detections),
            "image": {**stats, "image_id": ref.id},
            "model": detector.model_id,
            "accelerator": detector.health().accelerator}


@tools.tool(
    "vision_classify",
    "Classify an image or a detected region when a finer label than the "
    "detector's class list is needed — which kind of housing, which kind of "
    "switchgear. Optional stage; skip it when detection already answers the question.",
    {"type": "object", "additionalProperties": False,
     "properties": {"image_id": {"type": "string", "maxLength": 64},
                    "bbox": {"type": "array",
                             "description": "Optional [x1,y1,x2,y2] crop in pixels."}}},
    category="vision", needs_roles=["classifier"])
async def vision_classify(image_id: Optional[str] = None, bbox: Optional[List[float]] = None,
                          context: Dict[str, Any] = None):
    context = context or {}
    ref = _pick(image_id, context)
    classifier = models.classifier()
    if not classifier.is_ready():
        h = classifier.health()
        # §7 calls this stage optional, so its absence is a skip, not a failure.
        return {"classifications": [], "skipped": True, "degraded": True,
                "image_id": ref.id, "bbox": bbox, "model": h.model_id,
                "reason": h.reason or "no classification model available",
                "fallback": "detector label plus the reasoning model's own reading"}

    # With no bbox, classify the strongest detection's region if there is one:
    # a crop classifies far better than a whole scene.
    if bbox is None:
        detections = context.get("detections") or []
        if detections:
            bbox = detections[0].get("bbox")

    results = await classifier.classify(ref, bbox)
    return {"classifications": results, "count": len(results), "image_id": ref.id,
            "bbox": bbox, "model": classifier.model_id,
            "accelerator": classifier.health().accelerator}


@tools.tool(
    "vision_segment",
    "Segment a target in an image when its exact extent matters, for example "
    "to show which component is being discussed.",
    {"type": "object", "additionalProperties": False,
     "properties": {"image_id": {"type": "string", "maxLength": 64},
                    "target": {"type": "string", "maxLength": 120}}},
    category="vision", needs_roles=["segmenter"])
async def vision_segment(image_id: Optional[str] = None, target: Optional[str] = None,
                         context: Dict[str, Any] = None):
    ref = _pick(image_id, context or {})
    seg = models.segmenter()
    if not seg.is_ready():
        return {"segmented": False, "image_id": ref.id, "target": target, "degraded": True,
                "reason": seg.health().reason or "no segmentation model available",
                "fallback": "detector bounding box"}
    return {"segmented": True, **(await seg.segment(ref, target)), "image_id": ref.id}


@tools.tool(
    "vision_track",
    "Update the tracked target for the current live session using this frame's "
    "detections.",
    {"type": "object", "additionalProperties": False,
     "properties": {"image_id": {"type": "string", "maxLength": 64},
                    "target_label": {"type": "string", "maxLength": 120}}},
    category="vision", needs_roles=["tracker"])
async def vision_track(image_id: Optional[str] = None, target_label: Optional[str] = None,
                       context: Dict[str, Any] = None):
    context = context or {}
    ref = _pick(image_id, context)
    tracker = models.tracker()
    if not tracker.is_ready():
        return {"tracked": False, "degraded": True,
                "reason": tracker.health().reason or "no tracker available"}
    state = dict(context.get("track_state") or {})
    state["detections"] = context.get("detections") or []
    if target_label and not state.get("target"):
        match = next((d for d in state["detections"]
                      if d.get("label", "").lower() == target_label.lower()), None)
        if match:
            state["target"] = {"label": match["label"], "bbox": match["bbox"],
                               "confidence": match["confidence"], "misses": 0,
                               "track_id": "track_1"}
    return await tracker.track(ref, state)


@tools.tool(
    "ocr_extract",
    "Read text in an image: model and serial numbers, voltage and current "
    "ratings, warning labels, terminal markings, manufacturer names and error codes.",
    IMAGE_ARG, category="vision", needs_roles=["ocr"])
async def ocr_extract(image_id: Optional[str] = None, context: Dict[str, Any] = None):
    ref = _pick(image_id, context or {})
    ocr = models.ocr()
    if not ocr.is_ready():
        # §25: OCR unavailable -> the VLM attempts visual text understanding.
        return {"text_regions": [], "degraded": True, "image_id": ref.id,
                "reason": ocr.health().reason or "no OCR provider available",
                "fallback": "the reasoning model reads the label visually"}
    regions = await ocr.extract(ref)
    return {"text_regions": regions, "count": len(regions), "image_id": ref.id,
            "joined_text": " ".join(r["text"] for r in regions)[:2000],
            "model": ocr.model_id, "accelerator": ocr.health().accelerator}

"""Tracking adapters — Track-Anything / EdgeTAM (§3), plus a classical fallback.

§8 wants the tracker running continuously on the selected target while the
detector runs only periodically and the VLM only on events.  The classical
tracker below is a real IoU + centroid associator over detections: it costs
nothing, keeps a stable target id between detector passes, and is labelled
``cpu-classical`` so no one mistakes it for an accelerated model.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.errors import ModelUnavailable
from app.models.base import READY, ImageRef, ModelHealth, VisionTracker
from app.models.runtime import find_asset, load_onnx_session

FALLBACK = "centroid tracker"


def _iou(a: List[float], b: List[float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    denom = area_a + area_b - inter
    return inter / denom if denom > 0 else 0.0


class CentroidTracker(VisionTracker):
    """Associate this frame's detections with the target carried in ``state``.

    ``state`` is ``{"bbox": [...], "label": str, "misses": int, "track_id": str}``
    and is returned updated, so the caller (the live session) owns persistence
    and the tracker itself stays stateless and testable.
    """

    def __init__(self, max_misses: int = 12, min_iou: float = 0.15) -> None:
        super().__init__("centroid_tracker", "cpu-classical")
        self.max_misses = max_misses
        self.min_iou = min_iou

    def _load(self) -> None:
        self._health = ModelHealth(
            role=self.role, provider=self.provider, model_id=self.model_id, status=READY,
            runtime="numpy", accelerator="cpu", npu=False, synthetic=False,
            detail={"note": "Classical IoU/centroid association, not a learned tracker."},
        )

    async def track(self, frame: ImageRef, state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        self.require_ready()
        state = dict(state or {})
        detections: List[Dict[str, Any]] = state.get("detections") or []
        target = state.get("target")

        if target is None:
            if not detections:
                return {"tracked": False, "reason": "no target and no detections",
                        "model": self.model_id}
            best = max(detections, key=lambda d: d.get("confidence", 0.0))
            return {"tracked": True, "acquired": True, "target": {
                "track_id": state.get("track_id") or "track_1",
                "label": best.get("label"), "bbox": best.get("bbox"),
                "confidence": best.get("confidence"), "misses": 0,
            }, "model": self.model_id}

        prev_box = target.get("bbox") or [0, 0, 0, 0]
        scored = [(d, _iou(prev_box, d.get("bbox") or [0, 0, 0, 0])) for d in detections]
        scored = [s for s in scored if s[1] >= self.min_iou]
        if not scored:
            misses = int(target.get("misses", 0)) + 1
            lost = misses > self.max_misses
            return {
                "tracked": not lost,
                "lost": lost,
                "target": {**target, "misses": misses},
                "reason": "no overlapping detection this frame",
                "model": self.model_id,
            }
        best, iou = max(scored, key=lambda s: s[1])
        return {"tracked": True, "iou": round(iou, 4), "target": {
            "track_id": target.get("track_id", "track_1"),
            "label": best.get("label", target.get("label")),
            "bbox": best.get("bbox"),
            "confidence": best.get("confidence"),
            "misses": 0,
        }, "model": self.model_id}


class EdgeTAMTracker(VisionTracker):
    """ONNX EdgeTAM path for an exported Workbench asset."""

    def __init__(self, model_id: str = "edgetam") -> None:
        super().__init__(model_id, "edgetam-onnx")
        self._sess = None

    def _load(self) -> None:
        asset = find_asset(self.model_id, "model.onnx")
        if asset is None:
            raise ModelUnavailable(
                f"no ONNX asset under data/models/{self.model_id}/",
                model=self.model_id, fallback=FALLBACK,
            )
        loaded = load_onnx_session(asset)
        self._sess = loaded
        self._health = ModelHealth(
            role=self.role, provider=self.provider, model_id=self.model_id, status=READY,
            runtime="onnxruntime", accelerator=loaded.accelerator, npu=loaded.npu,
            asset_path=loaded.path, load_ms=loaded.load_ms,
            detail={"execution_providers": loaded.providers},
        )

    async def track(self, frame: ImageRef, state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        self.require_ready(fallback=FALLBACK)
        raise ModelUnavailable(
            "EdgeTAM session loads but its memory-bank I/O is bound after on-device export",
            model=self.model_id, fallback=FALLBACK,
        )

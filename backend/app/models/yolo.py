"""Object detection adapters — YOLO11-Detection / YOLO-WORLD (§3).

The ONNX path is complete and real: letterbox preprocessing, the YOLOv8/v11
head layout ``[1, 4+nc, n]``, class selection, NMS and coordinate unmapping.
Point ``data/models/yolov11_det/`` at an exported asset and it runs.

It is not enabled by guesswork: if the asset is absent, the adapter reports
``unavailable`` and the photo pipeline degrades to VLM-only inspection, which
is exactly the fallback §25 prescribes.

§4 note: Qualcomm currently lists YOLOv11-Detection, YOLO-WORLD and
YOLOv11-Segmentation with X-series metadata *and* a Compute-support
limitation.  Until a Workbench export/profile succeeds on the target device,
these stay experimental — see MODEL_STATUS.md.  The adapter reports the
accelerator the runtime actually gave it, never the one we hoped for.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import numpy as np

from app.config import settings
from app.errors import ModelUnavailable
from app.logging_setup import get_logger
from app.models._imaging import letterbox, nms, open_image
from app.models.base import READY, ImageRef, ModelHealth, VisionDetector
from app.models.runtime import find_asset, load_onnx_session, model_dir

log = get_logger(__name__)

COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier",
    "toothbrush",
]


class YoloOnnxDetector(VisionDetector):
    """ONNX Runtime detector. Works with any YOLOv8/v11-style export."""

    def __init__(self, model_id: Optional[str] = None, input_size: int = 640,
                 conf_threshold: float = 0.30, iou_threshold: float = 0.45) -> None:
        super().__init__(model_id or settings.detector_model_id, "yolo-onnx")
        self.input_size = input_size
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self._sess = None
        self._labels: List[str] = COCO_CLASSES

    def _load(self) -> None:
        asset = find_asset(self.model_id, "model.onnx", "yolov11_det.onnx")
        if asset is None:
            raise ModelUnavailable(
                f"no ONNX asset under data/models/{self.model_id}/",
                model=self.model_id, fallback="vlm-only inspection",
            )
        labels_file = model_dir(self.model_id) / "labels.json"
        if labels_file.exists():
            try:
                self._labels = json.loads(labels_file.read_text(encoding="utf-8"))
            except Exception:
                log.warning("labels.json for %s is not valid JSON; using COCO names", self.model_id)
        loaded = load_onnx_session(asset)
        self._sess = loaded
        self._health = ModelHealth(
            role=self.role, provider=self.provider, model_id=self.model_id, status=READY,
            runtime="onnxruntime", accelerator=loaded.accelerator, npu=loaded.npu,
            asset_path=loaded.path, load_ms=loaded.load_ms,
            detail={"execution_providers": loaded.providers, "input_size": self.input_size,
                    "classes": len(self._labels)},
        )

    def capabilities(self) -> Dict[str, Any]:
        return {**super().capabilities(), "open_vocabulary": False,
                "classes": len(self._labels), "input_size": self.input_size}

    async def detect(self, image: ImageRef) -> List[Dict[str, Any]]:
        self.require_ready(fallback="vlm-only inspection")
        img = open_image(image)
        blob, scale, dx, dy = letterbox(img, self.input_size)
        assert self._sess is not None
        out = self._sess.session.run(None, {self._sess.input_names[0]: blob})[0]
        return self._postprocess(np.asarray(out), scale, dx, dy, img.width, img.height)

    def _postprocess(self, raw: np.ndarray, scale: float, dx: int, dy: int,
                     w: int, h: int) -> List[Dict[str, Any]]:
        pred = raw[0] if raw.ndim == 3 else raw
        # Heads come either [4+nc, n] or [n, 4+nc]; orient to rows = anchors.
        if pred.shape[0] < pred.shape[1]:
            pred = pred.T
        if pred.shape[1] < 5:
            return []
        boxes_cxcywh = pred[:, :4]
        scores_all = pred[:, 4:]
        cls_idx = scores_all.argmax(axis=1)
        conf = scores_all.max(axis=1)
        keep_mask = conf >= self.conf_threshold
        if not keep_mask.any():
            return []
        boxes_cxcywh, conf, cls_idx = boxes_cxcywh[keep_mask], conf[keep_mask], cls_idx[keep_mask]

        cx, cy, bw, bh = boxes_cxcywh.T
        x1 = (cx - bw / 2 - dx) / scale
        y1 = (cy - bh / 2 - dy) / scale
        x2 = (cx + bw / 2 - dx) / scale
        y2 = (cy + bh / 2 - dy) / scale
        boxes = np.stack([
            np.clip(x1, 0, w), np.clip(y1, 0, h),
            np.clip(x2, 0, w), np.clip(y2, 0, h),
        ], axis=1)

        results: List[Dict[str, Any]] = []
        for i in nms(boxes, conf, self.iou_threshold):
            ci = int(cls_idx[i])
            label = self._labels[ci] if 0 <= ci < len(self._labels) else f"class_{ci}"
            bx = [round(float(v), 1) for v in boxes[i]]
            results.append({
                "label": label,
                "class_index": ci,
                "confidence": round(float(conf[i]), 4),
                "bbox": bx,
                "bbox_norm": [round(bx[0] / max(1, w), 4), round(bx[1] / max(1, h), 4),
                              round((bx[2] - bx[0]) / max(1, w), 4),
                              round((bx[3] - bx[1]) / max(1, h), 4)],
                "source": "detector",
                "model": self.model_id,
            })
        results.sort(key=lambda d: d["confidence"], reverse=True)
        return results[:50]


class YoloWorldDetector(YoloOnnxDetector):
    """Open-vocabulary variant.  Same runtime path, prompt-driven classes."""

    def __init__(self, model_id: str = "yolo_world", prompts: Optional[List[str]] = None) -> None:
        super().__init__(model_id)
        self.provider = "yolo-world-onnx"
        self._health.provider = self.provider
        self.prompts = prompts or []

    def capabilities(self) -> Dict[str, Any]:
        return {**super().capabilities(), "open_vocabulary": True, "prompts": self.prompts}

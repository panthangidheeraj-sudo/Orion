"""Image classification — EfficientNet-B4 (§3, §7).

An optional stage. §7's photo pipeline is

    detection -> optional classification -> OCR -> optional segmentation

so this runs only when a finer-grained label than the detector's class list is
worth having: telling a bearing housing from a gearbox housing, or a contactor
from a relay, once detection has found the region.

It is optional in the honest sense too — without an export the pipeline skips
it and says so, rather than guessing a class name.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from PIL import Image

from app.config import settings
from app.errors import ModelUnavailable
from app.logging_setup import get_logger
from app.models.base import READY, ImageRef, ModelHealth, VisionClassifier
from app.models.runtime import find_asset, load_onnx_session, model_dir

log = get_logger(__name__)

FALLBACK = "detector label plus the reasoning model's own reading of the image"

# ImageNet normalisation, which is what the AI Hub EfficientNet recipes expect.
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)


class EfficientNetOnnxClassifier(VisionClassifier):
    """ONNX Runtime classifier. Works with any B0–B7 export."""

    def __init__(self, model_id: Optional[str] = None, input_size: int = 380,
                 top_k: int = 5) -> None:
        super().__init__(model_id or settings.classifier_model_id, "efficientnet-onnx")
        self.input_size = input_size
        self.top_k = top_k
        self._sess = None
        self._labels: List[str] = []

    def _load(self) -> None:
        asset = find_asset(self.model_id, "model.onnx", "efficientnet_b4.onnx")
        if asset is None:
            raise ModelUnavailable(
                f"no ONNX asset under data/models/{self.model_id}/",
                model=self.model_id, fallback=FALLBACK,
            )
        labels_file = model_dir(self.model_id) / "labels.json"
        if labels_file.exists():
            try:
                self._labels = json.loads(labels_file.read_text(encoding="utf-8"))
            except Exception:
                log.warning("labels.json for %s is not valid JSON", self.model_id)
        loaded = load_onnx_session(asset)
        self._sess = loaded
        shape = loaded.session.get_inputs()[0].shape
        if isinstance(shape[-1], int) and shape[-1] > 32:
            self.input_size = int(shape[-1])
        self._health = ModelHealth(
            role=self.role, provider=self.provider, model_id=self.model_id, status=READY,
            runtime="onnxruntime", accelerator=loaded.accelerator, npu=loaded.npu,
            asset_path=loaded.path, load_ms=loaded.load_ms,
            detail={"execution_providers": loaded.providers,
                    "input_size": self.input_size,
                    "labels": len(self._labels) or "unlabelled — indices only"},
        )

    def capabilities(self) -> Dict[str, Any]:
        return {**super().capabilities(), "input_size": self.input_size,
                "top_k": self.top_k, "classes": len(self._labels) or None}

    async def classify(self, image: ImageRef,
                       bbox: Optional[Sequence[float]] = None) -> List[Dict[str, Any]]:
        self.require_ready(fallback=FALLBACK)
        img = Image.open(image.path).convert("RGB")
        if bbox and len(bbox) == 4:
            x1, y1, x2, y2 = (float(v) for v in bbox)
            x1, y1 = max(0.0, x1), max(0.0, y1)
            x2, y2 = min(float(img.width), x2), min(float(img.height), y2)
            if x2 - x1 >= 8 and y2 - y1 >= 8:
                img = img.crop((int(x1), int(y1), int(x2), int(y2)))

        img = img.resize((self.input_size, self.input_size), Image.BILINEAR)
        arr = np.asarray(img, dtype=np.float32).transpose(2, 0, 1) / 255.0
        blob = ((arr - MEAN) / STD)[None, ...]

        assert self._sess is not None
        logits = np.asarray(self._sess.session.run(None, {self._sess.input_names[0]: blob})[0])[0]
        exp = np.exp(logits - logits.max())
        probs = exp / exp.sum()
        order = probs.argsort()[::-1][: self.top_k]
        return [{
            "label": self._labels[int(i)] if int(i) < len(self._labels) else f"class_{int(i)}",
            "class_index": int(i),
            "confidence": round(float(probs[int(i)]), 4),
            "source": "classifier",
            "model": self.model_id,
        } for i in order]

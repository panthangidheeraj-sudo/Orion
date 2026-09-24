"""Segmentation adapters — SAM2 / MobileSAM / YOLO11-Segmentation (§3).

Used sparingly: §8 says segmentation runs only when needed, never per frame.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np

from app.config import settings
from app.errors import ModelUnavailable
from app.models._imaging import letterbox, open_image
from app.models.base import READY, ImageRef, ModelHealth, VisionSegmenter
from app.models.runtime import find_asset, load_onnx_session

FALLBACK = "detector bounding box"


class OnnxSegmenter(VisionSegmenter):
    """Generic ONNX segmentation session (YOLO11-seg / MobileSAM export)."""

    def __init__(self, model_id: str = "yolov11_seg", input_size: int = 640) -> None:
        super().__init__(model_id, "onnx-seg")
        self.input_size = input_size
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

    async def segment(self, image: ImageRef, target: Optional[str] = None) -> Dict[str, Any]:
        self.require_ready(fallback=FALLBACK)
        img = open_image(image)
        blob, scale, dx, dy = letterbox(img, self.input_size)
        assert self._sess is not None
        outputs = self._sess.session.run(None, {self._sess.input_names[0]: blob})
        proto = np.asarray(outputs[-1])
        return {
            "target": target,
            "model": self.model_id,
            "mask_prototypes": list(proto.shape),
            "image": {"width": img.width, "height": img.height},
            "letterbox": {"scale": round(scale, 5), "dx": dx, "dy": dy},
            "note": "Raw prototypes. Mask assembly is finished against the exported "
                    "head layout once a Workbench export is validated on device.",
            "source": image.source,
        }

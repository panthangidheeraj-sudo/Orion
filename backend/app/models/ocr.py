"""OCR adapters — EasyOCR / TrOCR (§3), producing the §9 record shape.

    {"text": "E17", "confidence": 0.97, "bbox": [120, 80, 220, 130],
     "source": "live_frame"}

When no OCR backend is installed the pipeline degrades to letting the VLM read
text visually (§25), and the adapter says so rather than returning nothing.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from app.config import settings
from app.errors import ModelUnavailable
from app.logging_setup import get_logger
from app.models.base import READY, ImageRef, ModelHealth, OCRProvider
from app.models.runtime import find_asset, load_onnx_session

log = get_logger(__name__)

FALLBACK = "vlm visual text reading"


class EasyOCRProvider(OCRProvider):
    """Wraps the ``easyocr`` package when it is installed locally."""

    def __init__(self, model_id: Optional[str] = None, languages: Optional[List[str]] = None):
        super().__init__(model_id or settings.ocr_model_id, "easyocr")
        self.languages = languages or ["en"]
        self._reader = None

    def _load(self) -> None:
        try:
            import easyocr  # type: ignore
        except Exception as exc:
            raise ModelUnavailable(
                f"easyocr not importable ({type(exc).__name__})",
                model=self.model_id, fallback=FALLBACK,
            )
        self._reader = easyocr.Reader(self.languages, gpu=False, verbose=False)
        self._health = ModelHealth(
            role=self.role, provider=self.provider, model_id=self.model_id, status=READY,
            runtime="easyocr", accelerator="cpu", npu=False,
            detail={"languages": self.languages,
                    "note": "CPU path. Replace with a Workbench-exported asset for NPU."},
        )

    async def extract(self, image: ImageRef) -> List[Dict[str, Any]]:
        self.require_ready(fallback=FALLBACK)

        def _run() -> List[Dict[str, Any]]:
            raw = self._reader.readtext(image.path)  # type: ignore[union-attr]
            out: List[Dict[str, Any]] = []
            for box, text, conf in raw:
                xs = [float(p[0]) for p in box]
                ys = [float(p[1]) for p in box]
                out.append({
                    "text": str(text).strip(),
                    "confidence": round(float(conf), 4),
                    "bbox": [round(min(xs), 1), round(min(ys), 1),
                             round(max(xs), 1), round(max(ys), 1)],
                    "source": image.source,
                    "model": self.model_id,
                })
            return [r for r in out if r["text"]]

        return await asyncio.to_thread(_run)


class TrOCROnnxProvider(OCRProvider):
    """ONNX TrOCR path for an exported Workbench asset."""

    def __init__(self, model_id: str = "trocr") -> None:
        super().__init__(model_id, "trocr-onnx")
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
            detail={"execution_providers": loaded.providers,
                    "note": "Recogniser only; pair with a text detector for bboxes."},
        )

    async def extract(self, image: ImageRef) -> List[Dict[str, Any]]:
        self.require_ready(fallback=FALLBACK)
        raise ModelUnavailable(
            "TrOCR recognition head is wired but the detection stage is not exported yet",
            model=self.model_id, fallback=FALLBACK,
        )

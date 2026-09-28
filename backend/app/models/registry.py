"""Adapter selection and the single source of truth for /api/models/status.

``auto`` walks a candidate list per role and keeps the first adapter that
actually loads.  Nothing is selected because it is configured — only because
it reported ``ready``.  The candidates that were tried and why they were
skipped stay in the status payload, so the model story is inspectable rather
than asserted (§4, §25).
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional

from app.config import settings
from app.logging_setup import get_logger
from app.models import base
from app.models.base import (
    Adapter, EmbeddingProvider, NoClassifier, NoDetector, NoEmbedding, NoOCR, NoReasoning,
    NoSTT, NoSegmenter, NoTTS, NoTracker, OCRProvider, ReasoningProvider,
    SpeechToTextProvider, TextToSpeechProvider, VisionClassifier, VisionDetector,
    VisionSegmenter, VisionTracker,
)
from app.models.classification import EfficientNetOnnxClassifier
from app.models.geniex import GenieXQwen3VLProvider
from app.models.embeddings import LexicalHashEmbedder, NomicOnnxEmbedder
from app.models.ocr import EasyOCRProvider, TrOCROnnxProvider
from app.models.qwen_vl import LocalOpenAICompatProvider, QwenVLGenAIProvider
from app.models.runtime import asset_inventory, runtime_info
from app.models.segmentation import OnnxSegmenter
from app.models.tracking import CentroidTracker, EdgeTAMTracker
from app.models.tts import PiperTTSProvider
from app.models.whisper import FasterWhisperProvider, WhisperOnnxProvider
from app.models.yolo import YoloOnnxDetector, YoloWorldDetector

log = get_logger(__name__)

Candidate = tuple  # (name, factory)


def _candidates() -> Dict[str, List[Candidate]]:
    """Ordered candidates per role. Highest capability first, honest last."""
    # Real language models only. There is deliberately no rule-based stand-in:
    # with no model running, Orion says it can't interpret requests rather than
    # pretending to (app/agent/router.py).
    #
    # geniex-qwen3-vl is Qwen3-VL-4B-Instruct on the Snapdragon NPU through
    # Qualcomm GenieX + QAIRT (app/models/geniex.py). On any machine without
    # GenieX it reports unavailable in milliseconds, so it can lead the list.
    reasoning: List[Candidate] = [
        ("geniex-qwen3-vl", GenieXQwen3VLProvider),
        ("onnxruntime-genai", QwenVLGenAIProvider),
        ("local-openai-compat", LocalOpenAICompatProvider),
    ]

    return {
        "reasoning": reasoning,
        "detector": [("yolo-onnx", YoloOnnxDetector), ("yolo-world-onnx", YoloWorldDetector)],
        "classifier": [("efficientnet-onnx", EfficientNetOnnxClassifier)],
        # §3 lists SAM2, MobileSAM and YOLO11-Seg as segmentation candidates. They
        # share the ONNX session path, so each is the same adapter pointed at a
        # different exported asset — selectable by name, not hard-wired.
        "segmenter": [
            ("onnx-seg", lambda: OnnxSegmenter(settings.segmenter_model_id)),
            ("sam2-onnx", lambda: OnnxSegmenter("sam2")),
            ("mobilesam-onnx", lambda: OnnxSegmenter("mobilesam")),
        ],
        "tracker": [
            ("edgetam-onnx", lambda: EdgeTAMTracker(settings.tracker_model_id)),
            ("track-anything-onnx", lambda: EdgeTAMTracker("track_anything")),
            ("cpu-classical", CentroidTracker),
        ],
        "ocr": [("easyocr", EasyOCRProvider), ("trocr-onnx", TrOCROnnxProvider)],
        "embedding": [
            ("nomic-onnx", lambda: NomicOnnxEmbedder(settings.embedding_model_id)),
            ("minilm-onnx", lambda: NomicOnnxEmbedder("minilm_v2", dim=384)),
            ("lexical-hash", LexicalHashEmbedder),
        ],
        "stt": [("whisper-onnx", WhisperOnnxProvider), ("faster-whisper", FasterWhisperProvider)],
        "tts": [("piper", PiperTTSProvider)],
    }


NULLS: Dict[str, Callable[[], Adapter]] = {
    "reasoning": lambda: NoReasoning(settings.reasoning_model_id, "none"),
    "detector": lambda: NoDetector(settings.detector_model_id, "none"),
    "classifier": lambda: NoClassifier(settings.classifier_model_id, "none"),
    "segmenter": lambda: NoSegmenter(settings.segmenter_model_id, "none"),
    "tracker": lambda: NoTracker(settings.tracker_model_id, "none"),
    "ocr": lambda: NoOCR(settings.ocr_model_id, "none"),
    "embedding": lambda: NoEmbedding(settings.embedding_model_id, "none"),
    "stt": lambda: NoSTT(settings.stt_model_id, "none"),
    "tts": lambda: NoTTS(settings.tts_model_id, "none"),
}

PREFERENCE = {
    "reasoning": lambda: settings.reasoning_provider,
    "detector": lambda: settings.detector_provider,
    "classifier": lambda: settings.classifier_provider,
    "segmenter": lambda: settings.segmenter_provider,
    "tracker": lambda: settings.tracker_provider,
    "ocr": lambda: settings.ocr_provider,
    "embedding": lambda: settings.embedding_provider,
    "stt": lambda: settings.stt_provider,
    "tts": lambda: settings.tts_provider,
}


class ModelRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._chosen: Dict[str, Adapter] = {}
        self._attempts: Dict[str, List[Dict[str, Any]]] = {}
        self._probed_at: Dict[str, float] = {}

    # ------------------------------------------------------------- selection
    def _select(self, role: str) -> Adapter:
        pref = PREFERENCE[role]()
        options = _candidates()[role]
        attempts: List[Dict[str, Any]] = []
        if pref and pref != "auto":
            # An explicitly chosen provider is the only one tried: if it cannot
            # run, the role is unavailable — never silently another model.
            chosen = [o for o in options if o[0] == pref]
            if not chosen:
                self._attempts[role] = [{
                    "provider": pref, "status": "error",
                    "reason": f"unknown provider '{pref}'; known: "
                              + ", ".join(o[0] for o in options)}]
                log.warning("role=%s: unknown provider %r", role, pref)
                return NULLS[role]()
            options = chosen
        for name, factory in options:
            try:
                adapter = factory()
            except Exception as exc:
                attempts.append({"provider": name, "status": "error",
                                 "reason": f"{type(exc).__name__}: {exc}"})
                continue
            h = adapter.health()
            attempts.append({"provider": name, "status": h.status, "reason": h.reason,
                             "model_id": h.model_id})
            if h.status == base.READY:
                self._attempts[role] = attempts
                log.info("role=%s provider=%s model=%s accelerator=%s npu=%s synthetic=%s",
                         role, name, h.model_id, h.accelerator, h.npu, h.synthetic)
                return adapter
        self._attempts[role] = attempts
        log.warning("role=%s has no working adapter; degrading per spec §25", role)
        return NULLS[role]()

    def get(self, role: str) -> Adapter:
        with self._lock:
            if role not in self._chosen:
                self._chosen[role] = self._select(role)
            return self._chosen[role]

    def refresh_if_unavailable(self, role: str, min_interval_s: float = 20.0) -> None:
        """Re-probe a role that has no working adapter, so a local model server
        started after the backend is picked up without a restart."""
        import time

        with self._lock:
            adapter = self._chosen.get(role)
            if adapter is None or adapter.health().status == base.READY:
                return
            now = time.monotonic()
            if now - self._probed_at.get(role, 0.0) < min_interval_s:
                return
            self._probed_at[role] = now
            self._chosen.pop(role, None)

    def reload(self) -> None:
        with self._lock:
            self._chosen.clear()
            self._attempts.clear()
        runtime_info(refresh=True)

    # ------------------------------------------------------ typed accessors
    def reasoning(self) -> ReasoningProvider:
        return self.get("reasoning")  # type: ignore[return-value]

    def detector(self) -> VisionDetector:
        return self.get("detector")  # type: ignore[return-value]

    def classifier(self) -> VisionClassifier:
        return self.get("classifier")  # type: ignore[return-value]

    def segmenter(self) -> VisionSegmenter:
        return self.get("segmenter")  # type: ignore[return-value]

    def tracker(self) -> VisionTracker:
        return self.get("tracker")  # type: ignore[return-value]

    def ocr(self) -> OCRProvider:
        return self.get("ocr")  # type: ignore[return-value]

    def embedding(self) -> EmbeddingProvider:
        return self.get("embedding")  # type: ignore[return-value]

    def stt(self) -> SpeechToTextProvider:
        return self.get("stt")  # type: ignore[return-value]

    def tts(self) -> TextToSpeechProvider:
        return self.get("tts")  # type: ignore[return-value]

    # ------------------------------------------------------------- reporting
    def status(self) -> Dict[str, Any]:
        # A local model server may have come up since the last probe.
        self.refresh_if_unavailable("reasoning")
        roles: Dict[str, Any] = {}
        for role in PREFERENCE:
            adapter = self.get(role)
            h = adapter.health()
            roles[role] = {
                **h.to_dict(),
                "capabilities": adapter.capabilities(),
                "candidates_tried": self._attempts.get(role, []),
            }
        ready = [r for r, v in roles.items() if v["status"] == base.READY]
        synthetic = [r for r, v in roles.items() if v.get("synthetic")]
        npu = [r for r, v in roles.items() if v.get("npu")]
        return {
            "roles": roles,
            "summary": {
                "ready": ready,
                "unavailable": [r for r in roles if r not in ready],
                "synthetic": synthetic,
                "npu_accelerated": npu,
                "npu_claim": bool(npu),
            },
            "runtime": runtime_info().to_dict(),
            "assets": asset_inventory(),
            "notice": (
                "Accelerator values come from what the runtime reported after each "
                "session loaded, not from configuration. Roles listed under "
                "'synthetic' are deterministic local stand-ins, not neural models, "
                "and make no NPU claim. See MODEL_STATUS.md."
            ),
        }


registry = ModelRegistry()

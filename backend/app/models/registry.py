"""Adapter selection and the single source of truth for /api/models/status.

``auto`` walks a candidate list per role and keeps the first adapter that
actually loads.  Nothing is selected because it is configured — only because
it reported ``ready``.  The candidates that were tried and why they were
skipped stay in the status payload, so the model story is inspectable rather
than asserted (§4, §25).
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List

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
from app.models.geniex import GenieXQwen3VLProvider, display_name as geniex_display_name
from app.models.hosted import HostedGroqProvider, PROVIDER as HOSTED_PROVIDER
from app.models.embeddings import LexicalHashEmbedder, NomicOnnxEmbedder
from app.models.ocr import EasyOCRProvider, TrOCROnnxProvider
from app.models.qwen_vl import LocalOpenAICompatProvider, QwenVLGenAIProvider
from app.models import remote
from app.models.remote import (
    PROVIDER as REMOTE_PROVIDER, RemoteClassifier, RemoteDetector, RemoteOCR, RemoteSegmenter,
    RemoteTracker,
)
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
        # Groq-hosted model over an OpenAI-compatible API — only when its key is set.
        (HOSTED_PROVIDER, HostedGroqProvider),
        ("onnxruntime-genai", QwenVLGenAIProvider),
        ("local-openai-compat", LocalOpenAICompatProvider),
    ]

    return {
        "reasoning": reasoning,
        # The trailing remote-vision entries are the Render split: the private
        # orion-vision service. They sit after every in-process adapter, so a
        # Snapdragon device (no VF_VISION_URL) behaves exactly as before.
        "detector": [("yolo-onnx", YoloOnnxDetector), ("yolo-world-onnx", YoloWorldDetector),
                     (REMOTE_PROVIDER, RemoteDetector)],
        "classifier": [("efficientnet-onnx", EfficientNetOnnxClassifier),
                       (REMOTE_PROVIDER, RemoteClassifier)],
        # §3 lists SAM2, MobileSAM and YOLO11-Seg as segmentation candidates. They
        # share the ONNX session path, so each is the same adapter pointed at a
        # different exported asset — selectable by name, not hard-wired.
        "segmenter": [
            ("onnx-seg", lambda: OnnxSegmenter(settings.segmenter_model_id)),
            ("sam2-onnx", lambda: OnnxSegmenter("sam2")),
            ("mobilesam-onnx", lambda: OnnxSegmenter("mobilesam")),
            (REMOTE_PROVIDER, RemoteSegmenter),
        ],
        "tracker": [
            ("edgetam-onnx", lambda: EdgeTAMTracker(settings.tracker_model_id)),
            ("track-anything-onnx", lambda: EdgeTAMTracker("track_anything")),
            ("cpu-classical", CentroidTracker),
            # After the free classical tracker on purpose: "auto" never pays a network
            # hop for it. Pin VF_TRACKER_PROVIDER=remote-vision to use the service's.
            (REMOTE_PROVIDER, RemoteTracker),
        ],
        "ocr": [("easyocr", EasyOCRProvider), ("trocr-onnx", TrOCROnnxProvider),
                (REMOTE_PROVIDER, RemoteOCR)],
        "embedding": [
            ("nomic-onnx", lambda: NomicOnnxEmbedder(settings.embedding_model_id)),
            ("minilm-onnx", lambda: NomicOnnxEmbedder("minilm_v2", dim=384)),
            ("lexical-hash", LexicalHashEmbedder),
        ],
        "stt": [("whisper-onnx", WhisperOnnxProvider), ("faster-whisper", FasterWhisperProvider)],
        "tts": [("piper", PiperTTSProvider)],
    }


NULLS: Dict[str, Callable[[], Adapter]] = {
    # With GenieX pinned, an unavailable role still names the model it is waiting for.
    "reasoning": lambda: NoReasoning(
        geniex_display_name(settings.geniex_model)
        if settings.reasoning_provider == "geniex-qwen3-vl"
        else settings.hosted_llm_model if settings.reasoning_provider == HOSTED_PROVIDER
        else settings.reasoning_model_id, "none"),
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
        if role in remote.VISION_ROLES and remote.configured() and pref in ("", "auto", REMOTE_PROVIDER):
            # The vision service is configured but not ready right now. Keep the remote
            # adapter: its health is live, so the role reports the real reason and
            # turns READY by itself when the service comes back — never before.
            factory = next(f for n, f in _candidates()[role] if n == REMOTE_PROVIDER)
            return factory()
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
            # A pinned GenieX bundle doesn't appear on its own, and each attempt
            # can map gigabytes of context binaries — retry only on an explicit
            # POST /api/models/reload, never on a status poll.
            if PREFERENCE[role]() == "geniex-qwen3-vl":
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
        remote.client.reset()
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
    @staticmethod
    def _ai(r: Dict[str, Any]) -> Dict[str, Any]:
        """The one-glance answer to "what is answering, and where does it run?"."""
        ready = r.get("status") == base.READY
        hosted = bool(r.get("hosted"))
        npu = bool(r.get("npu")) and not hosted
        return {
            "status": r.get("status", base.UNAVAILABLE),
            "mode": ("hosted" if hosted else "local") if ready else "unavailable",
            "provider": r.get("provider"),
            # What this deployment is configured to use ("auto" when it decides at runtime).
            "configured_provider": settings.reasoning_provider,
            "model_id": r.get("model_id"),
            "accelerator": r.get("accelerator", "none"),
            "npu": npu,
            "hosted": hosted,
            "synthetic": bool(r.get("synthetic")),
            # The real cause is on the candidate that was tried, not on the placeholder.
            "reason": None if ready else next(
                (c["reason"] for c in r.get("candidates_tried", []) if c.get("reason")),
                r.get("reason")),
        }

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
            "ai": self._ai(roles.get("reasoning", {})),
            "roles": roles,
            # The private vision service, when this deployment uses one.
            "services": {"vision": remote.client.summary()},
            "summary": {
                "ready": ready,
                "unavailable": [r for r in roles if r not in ready],
                "synthetic": synthetic,
                "npu_accelerated": npu,
                "npu_claim": bool(npu),
                "hosted": [r for r, v in roles.items() if v.get("hosted")],
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

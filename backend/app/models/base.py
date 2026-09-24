"""Model adapter interfaces (§6).

Nothing outside this package may import a model library.  The agent talks to
these eight interfaces and to nothing else, so a model can be swapped, or turn
out to be unsupported on Snapdragon Compute (§4), without the agent changing.

Two rules govern every adapter in this package:

1.  An adapter that cannot load reports ``unavailable`` and raises
    :class:`app.errors.ModelUnavailable` with the §25 envelope.  It never
    returns plausible-looking output instead.
2.  An adapter reports the accelerator it *actually* got from the runtime,
    never the one that was requested.  §4: never fake Snapdragon/NPU support.
"""

from __future__ import annotations

import abc
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from app.errors import ModelUnavailable

READY = "ready"
UNAVAILABLE = "unavailable"
ERROR = "error"


@dataclass
class ModelHealth:
    """What is true about this adapter right now.

    ``npu`` is only ever True when the runtime confirmed an NPU execution
    provider was applied to a session that actually loaded.
    """

    role: str
    provider: str
    model_id: str
    status: str = UNAVAILABLE
    runtime: str = "none"
    accelerator: str = "none"
    npu: bool = False
    synthetic: bool = False
    reason: Optional[str] = None
    asset_path: Optional[str] = None
    load_ms: Optional[float] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Adapter(abc.ABC):
    """Common behaviour: identity, health, capabilities, lazy load."""

    role: str = "unknown"

    def __init__(self, model_id: str, provider: str) -> None:
        self.model_id = model_id
        self.provider = provider
        self._health = ModelHealth(role=self.role, provider=provider, model_id=model_id)
        self._loaded = False

    # -- subclasses override ------------------------------------------------
    def _load(self) -> None:  # pragma: no cover - default is "nothing to load"
        self._health.status = READY

    def capabilities(self) -> Dict[str, Any]:
        return {"role": self.role, "provider": self.provider, "model_id": self.model_id}

    # -- shared -------------------------------------------------------------
    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        try:
            self._load()
        except ModelUnavailable as exc:
            self._health.status = UNAVAILABLE
            self._health.reason = exc.reason
        except Exception as exc:  # defensive: a broken asset must not kill the app
            self._health.status = ERROR
            self._health.reason = f"{type(exc).__name__}: {exc}"
        finally:
            self._loaded = True

    def health(self) -> ModelHealth:
        self.ensure_loaded()
        return self._health

    def is_ready(self) -> bool:
        return self.health().status == READY

    def require_ready(self, fallback: Optional[str] = None) -> None:
        h = self.health()
        if h.status != READY:
            raise ModelUnavailable(
                h.reason or "adapter not loaded",
                model=self.model_id,
                fallback=fallback,
                role=self.role,
                provider=self.provider,
            )


# --------------------------------------------------------------------- roles

class VisionDetector(Adapter):
    role = "detector"

    @abc.abstractmethod
    async def detect(self, image: "ImageRef") -> List[Dict[str, Any]]:
        """Return detections: label, confidence, bbox [x1,y1,x2,y2] in pixels."""


class VisionClassifier(Adapter):
    role = "classifier"

    @abc.abstractmethod
    async def classify(self, image: "ImageRef",
                       bbox: Optional[Sequence[float]] = None) -> List[Dict[str, Any]]:
        """Return ranked labels for the image or a crop of it."""


class VisionSegmenter(Adapter):
    role = "segmenter"

    @abc.abstractmethod
    async def segment(self, image: "ImageRef", target: Optional[str] = None) -> Dict[str, Any]:
        ...


class VisionTracker(Adapter):
    role = "tracker"

    @abc.abstractmethod
    async def track(self, frame: "ImageRef", state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        ...


class OCRProvider(Adapter):
    role = "ocr"

    @abc.abstractmethod
    async def extract(self, image: "ImageRef") -> List[Dict[str, Any]]:
        """Return §9 records: text, confidence, bbox, source."""


class ReasoningProvider(Adapter):
    role = "reasoning"

    @abc.abstractmethod
    async def generate(
        self,
        messages: Sequence[Dict[str, Any]],
        images: Optional[Sequence["ImageRef"]] = None,
        tools: Optional[Sequence[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return {"text": str, "tool_calls": [...], "usage": {...}}."""

    async def stream(self, messages, images=None, tools=None, context=None):
        """Default streaming: one chunk.  Real adapters override."""
        result = await self.generate(messages, images=images, tools=tools, context=context)
        yield {"type": "text", "value": result.get("text", "")}
        yield {"type": "done", "value": result}

    def supports_streaming(self) -> bool:
        return False


class EmbeddingProvider(Adapter):
    role = "embedding"
    dim: int = 0

    @abc.abstractmethod
    async def embed(self, texts: Sequence[str]) -> List[List[float]]:
        ...


class SpeechToTextProvider(Adapter):
    role = "stt"

    @abc.abstractmethod
    async def transcribe(self, audio: bytes, mime_type: str = "audio/wav") -> Dict[str, Any]:
        ...


class TextToSpeechProvider(Adapter):
    role = "tts"

    @abc.abstractmethod
    async def synthesize(self, text: str, voice: Optional[str] = None) -> Dict[str, Any]:
        ...


# ------------------------------------------------------------------ image ref

@dataclass
class ImageRef:
    """A picture the pipeline is allowed to touch.

    Vision adapters never take a path from the caller.  They take one of these,
    which the storage layer produced from a validated, contained path, so a
    tool argument can never point the models at an arbitrary file (§15).
    """

    id: str
    path: str
    width: int = 0
    height: int = 0
    mime_type: str = "image/jpeg"
    source: str = "photo"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ------------------------------------------------------------- null adapters

class _Null:
    """Mixin producing the §25 structured error for an absent model."""

    def _fail(self, fallback: Optional[str] = None):
        h = self.health()  # type: ignore[attr-defined]
        raise ModelUnavailable(
            h.reason or "no adapter configured",
            model=self.model_id,  # type: ignore[attr-defined]
            fallback=fallback,
            role=self.role,  # type: ignore[attr-defined]
        )


def _unavailable(cls_name: str, base, reason: str):
    """Build an adapter class that is honest about doing nothing."""

    async def _raise(self, *a, **k):
        self._fail()

    ns = {
        "__doc__": f"Placeholder {base.role} adapter: {reason}",
        "_load": lambda self: setattr(self._health, "reason", reason),
    }
    for name in ("detect", "classify", "segment", "track", "extract", "generate",
                 "embed", "transcribe", "synthesize"):
        if getattr(base, name, None) is not None and name in getattr(base, "__abstractmethods__", ()):
            ns[name] = _raise
    return type(cls_name, (_Null, base), ns)


NoDetector = _unavailable("NoDetector", VisionDetector, "no detector asset configured")
NoClassifier = _unavailable("NoClassifier", VisionClassifier,
                            "no classification asset configured")
NoSegmenter = _unavailable("NoSegmenter", VisionSegmenter, "no segmentation asset configured")
NoTracker = _unavailable("NoTracker", VisionTracker, "no tracker asset configured")
NoOCR = _unavailable("NoOCR", OCRProvider, "no OCR asset configured")
NoReasoning = _unavailable("NoReasoning", ReasoningProvider, "no reasoning model asset configured")
NoEmbedding = _unavailable("NoEmbedding", EmbeddingProvider, "no embedding asset configured")
NoSTT = _unavailable("NoSTT", SpeechToTextProvider, "no speech-to-text asset configured")
NoTTS = _unavailable("NoTTS", TextToSpeechProvider, "no text-to-speech asset configured")

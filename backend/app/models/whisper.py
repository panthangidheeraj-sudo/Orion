"""Speech-to-text adapter — Whisper-Base (§17).

§17: "Do not require cloud speech services for the core path."  There is no
network fallback here by design; if no local Whisper asset is present the
adapter says so and the front-end keeps its own on-device recogniser or text
entry.  It never posts audio anywhere (§24).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import settings
from app.errors import ModelUnavailable
from app.models.base import READY, ModelHealth, SpeechToTextProvider
from app.models.runtime import find_asset, load_onnx_session, model_dir

FALLBACK = "front-end speech recognition or typed input"


class WhisperOnnxProvider(SpeechToTextProvider):
    """Encoder/decoder ONNX pair as exported by the AI Hub whisper_base recipe."""

    def __init__(self, model_id: Optional[str] = None) -> None:
        super().__init__(model_id or settings.stt_model_id, "whisper-onnx")
        self._encoder = None
        self._decoder = None

    def _load(self) -> None:
        root = model_dir(self.model_id)
        enc = find_asset(self.model_id, "encoder.onnx", "whisper_encoder.onnx")
        dec = (root / "decoder.onnx") if (root / "decoder.onnx").exists() else None
        if enc is None or dec is None:
            raise ModelUnavailable(
                f"whisper encoder/decoder pair not found under data/models/{self.model_id}/",
                model=self.model_id, fallback=FALLBACK,
            )
        self._encoder = load_onnx_session(enc)
        self._decoder = load_onnx_session(dec)
        self._health = ModelHealth(
            role=self.role, provider=self.provider, model_id=self.model_id, status=READY,
            runtime="onnxruntime", accelerator=self._encoder.accelerator,
            npu=self._encoder.npu and self._decoder.npu,
            asset_path=self._encoder.path,
            load_ms=round(self._encoder.load_ms + self._decoder.load_ms, 2),
            detail={"encoder_providers": self._encoder.providers,
                    "decoder_providers": self._decoder.providers},
        )

    async def transcribe(self, audio: bytes, mime_type: str = "audio/wav") -> Dict[str, Any]:
        self.require_ready(fallback=FALLBACK)
        raise ModelUnavailable(
            "Whisper sessions load but the mel front-end and decode loop are bound "
            "to the exported asset's I/O signature on device",
            model=self.model_id, fallback=FALLBACK,
        )


class FasterWhisperProvider(SpeechToTextProvider):
    """Optional CPU path via the ``faster_whisper`` package, if installed."""

    def __init__(self, model_id: str = "whisper_base", size: str = "base") -> None:
        super().__init__(model_id, "faster-whisper")
        self.size = size
        self._model = None

    def _load(self) -> None:
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except Exception as exc:
            raise ModelUnavailable(
                f"faster_whisper not importable ({type(exc).__name__})",
                model=self.model_id, fallback=FALLBACK,
            )
        self._model = WhisperModel(self.size, device="cpu", compute_type="int8")
        self._health = ModelHealth(
            role=self.role, provider=self.provider, model_id=self.model_id, status=READY,
            runtime="faster-whisper", accelerator="cpu", npu=False,
            detail={"size": self.size, "note": "CPU int8 path, no NPU involvement."},
        )

    async def transcribe(self, audio: bytes, mime_type: str = "audio/wav") -> Dict[str, Any]:
        self.require_ready(fallback=FALLBACK)
        tmp = settings.audio_dir / f"stt_{abs(hash(audio)) % (10 ** 12)}.bin"

        def _run() -> Dict[str, Any]:
            tmp.write_bytes(audio)
            try:
                segments, info = self._model.transcribe(str(tmp), beam_size=1)  # type: ignore
                parts = [{"start": round(s.start, 2), "end": round(s.end, 2),
                          "text": s.text.strip()} for s in segments]
                return {
                    "text": " ".join(p["text"] for p in parts).strip(),
                    "segments": parts,
                    "language": getattr(info, "language", None),
                    "model": self.model_id,
                }
            finally:
                try:
                    tmp.unlink()
                except OSError:
                    pass

        return await asyncio.to_thread(_run)

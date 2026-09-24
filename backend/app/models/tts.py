"""Text-to-speech adapter — PiperTTS-EN (§17).

§25: if TTS is unavailable the text response still stands, so the caller gets
a structured "spoken text is ready, audio is not" answer rather than an error
that breaks the conversation.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from typing import Any, Dict, Optional

from app.config import settings
from app.errors import ModelUnavailable
from app.logging_setup import get_logger
from app.models.base import READY, ModelHealth, TextToSpeechProvider
from app.models.runtime import model_dir
from app.util import new_id, preview

log = get_logger(__name__)
FALLBACK = "text response only"
MAX_CHARS = 1200


class PiperTTSProvider(TextToSpeechProvider):
    """Drives a local ``piper`` binary with a voice model from data/models/.

    The binary is invoked with an argument list (never a shell string) and only
    with paths this process created, so nothing user-supplied can reach a
    shell (§15, §24).
    """

    def __init__(self, model_id: Optional[str] = None) -> None:
        super().__init__(model_id or settings.tts_model_id, "piper")
        self._binary: Optional[str] = None
        self._voice = None

    def _load(self) -> None:
        binary = shutil.which("piper")
        root = model_dir(self.model_id)
        voices = sorted(root.glob("*.onnx")) if root.exists() else []
        if binary is None:
            raise ModelUnavailable("piper binary not on PATH", model=self.model_id,
                                   fallback=FALLBACK)
        if not voices:
            raise ModelUnavailable(
                f"no piper voice (*.onnx) under data/models/{self.model_id}/",
                model=self.model_id, fallback=FALLBACK,
            )
        self._binary, self._voice = binary, voices[0]
        self._health = ModelHealth(
            role=self.role, provider=self.provider, model_id=self.model_id, status=READY,
            runtime="piper", accelerator="cpu", npu=False, asset_path=str(voices[0]),
            detail={"binary": binary, "voice": voices[0].name},
        )

    async def synthesize(self, text: str, voice: Optional[str] = None) -> Dict[str, Any]:
        self.require_ready(fallback=FALLBACK)
        clipped = (text or "").strip()[:MAX_CHARS]
        if not clipped:
            return {"audio_path": None, "reason": "nothing to speak", "model": self.model_id}
        out = settings.audio_dir / f"{new_id('tts')}.wav"

        def _run() -> Dict[str, Any]:
            proc = subprocess.run(
                [self._binary, "--model", str(self._voice), "--output_file", str(out)],
                input=clipped.encode("utf-8"),
                capture_output=True, timeout=60, shell=False,
            )
            if proc.returncode != 0 or not out.exists():
                log.warning("piper failed rc=%s: %s", proc.returncode,
                            preview(proc.stderr.decode("utf-8", "ignore")))
                raise ModelUnavailable("piper synthesis failed", model=self.model_id,
                                       fallback=FALLBACK)
            return {
                "audio_path": str(out),
                "audio_id": out.stem,
                "mime_type": "audio/wav",
                "bytes": out.stat().st_size,
                "characters": len(clipped),
                "model": self.model_id,
            }

        return await asyncio.to_thread(_run)

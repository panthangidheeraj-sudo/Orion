"""Embedding adapters — Nomic-Embed-Text / MiniLM-v2 (§12), plus a lexical
fallback so local RAG keeps working before any model asset is exported.

The fallback is a hashed character-n-gram + word bag projected onto a fixed
number of dimensions and L2-normalised.  It is a real lexical embedding and it
retrieves usefully on technical text (part numbers, error codes, terminal
markings), but it is *not* a neural embedding, so it is flagged
``synthetic: true`` everywhere it surfaces.  §4's spirit applies: say what it
actually is.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from app.config import settings
from app.errors import ModelUnavailable
from app.models.base import READY, EmbeddingProvider, ModelHealth
from app.models.runtime import find_asset, load_onnx_session, model_dir

_WORD = re.compile(r"[a-z0-9][a-z0-9._/+-]*", re.I)

# Dropped so shared English filler does not dominate the similarity between
# two unrelated technical passages.
_STOP = frozenset(
    "a an and are as at be been by for from had has have in into is it its of on "
    "or that the their then there these this to was were what when which will with "
    "you your we our i not no if can could should would do does did".split()
)


class NomicOnnxEmbedder(EmbeddingProvider):
    """ONNX Runtime text embedder for an exported Nomic/MiniLM asset."""

    def __init__(self, model_id: Optional[str] = None, dim: int = 768,
                 max_tokens: int = 512) -> None:
        super().__init__(model_id or settings.embedding_model_id, "nomic-onnx")
        self.dim = dim
        self.max_tokens = max_tokens
        self._sess = None
        self._tokenizer = None

    def _load(self) -> None:
        asset = find_asset(self.model_id, "model.onnx")
        if asset is None:
            raise ModelUnavailable(
                f"no ONNX asset under data/models/{self.model_id}/",
                model=self.model_id, fallback="lexical-hash embedder",
            )
        try:
            from tokenizers import Tokenizer  # type: ignore

            tok_file = model_dir(self.model_id) / "tokenizer.json"
            if not tok_file.exists():
                raise ModelUnavailable(
                    "tokenizer.json missing beside the ONNX asset",
                    model=self.model_id, fallback="lexical-hash embedder",
                )
            self._tokenizer = Tokenizer.from_file(str(tok_file))
        except ModelUnavailable:
            raise
        except Exception as exc:
            raise ModelUnavailable(
                f"tokenizers not importable ({type(exc).__name__})",
                model=self.model_id, fallback="lexical-hash embedder",
            )
        loaded = load_onnx_session(asset)
        self._sess = loaded
        out_shape = loaded.session.get_outputs()[0].shape
        if isinstance(out_shape[-1], int):
            self.dim = int(out_shape[-1])
        self._health = ModelHealth(
            role=self.role, provider=self.provider, model_id=self.model_id, status=READY,
            runtime="onnxruntime", accelerator=loaded.accelerator, npu=loaded.npu,
            asset_path=loaded.path, load_ms=loaded.load_ms,
            detail={"execution_providers": loaded.providers, "dim": self.dim},
        )

    def capabilities(self) -> Dict[str, Any]:
        return {**super().capabilities(), "dim": self.dim, "max_tokens": self.max_tokens}

    async def embed(self, texts: Sequence[str]) -> List[List[float]]:
        self.require_ready(fallback="lexical-hash embedder")

        def _run() -> List[List[float]]:
            assert self._sess is not None and self._tokenizer is not None
            encoded = [self._tokenizer.encode(t or "") for t in texts]
            width = max(1, min(self.max_tokens, max(len(e.ids) for e in encoded)))
            ids = np.zeros((len(encoded), width), dtype=np.int64)
            mask = np.zeros((len(encoded), width), dtype=np.int64)
            for i, e in enumerate(encoded):
                n = min(width, len(e.ids))
                ids[i, :n] = e.ids[:n]
                mask[i, :n] = 1
            feeds: Dict[str, Any] = {}
            for name in self._sess.input_names:
                if "mask" in name:
                    feeds[name] = mask
                elif "token_type" in name:
                    feeds[name] = np.zeros_like(ids)
                else:
                    feeds[name] = ids
            out = np.asarray(self._sess.session.run(None, feeds)[0])
            if out.ndim == 3:  # mean-pool token states over the attention mask
                m = mask[..., None].astype(np.float32)
                out = (out * m).sum(axis=1) / np.maximum(1e-9, m.sum(axis=1))
            norms = np.linalg.norm(out, axis=1, keepdims=True)
            out = out / np.maximum(1e-9, norms)
            return [[round(float(v), 6) for v in row] for row in out]

        return await asyncio.to_thread(_run)


class LexicalHashEmbedder(EmbeddingProvider):
    """Deterministic lexical embedding. No model file, no network, no NPU claim."""

    def __init__(self, dim: int = 384) -> None:
        super().__init__("lexical_hash_v1", "lexical-hash")
        self.dim = dim

    def _load(self) -> None:
        self._health = ModelHealth(
            role=self.role, provider=self.provider, model_id=self.model_id, status=READY,
            runtime="numpy", accelerator="cpu", npu=False, synthetic=True,
            detail={
                "dim": self.dim,
                "note": "Stop-filtered hashed word + character-trigram bag. Keeps local RAG working "
                        "before a Nomic/MiniLM asset is exported; replace for semantic recall.",
            },
        )

    def capabilities(self) -> Dict[str, Any]:
        return {**super().capabilities(), "dim": self.dim, "semantic": False, "synthetic": True}

    def _vector(self, text: str) -> List[float]:
        vec = np.zeros(self.dim, dtype=np.float32)
        low = (text or "").lower()
        words = _WORD.findall(low)
        for w in words:
            if w in _STOP:
                continue
            h = int.from_bytes(hashlib.blake2b(w.encode(), digest_size=8).digest(), "little")
            vec[h % self.dim] += 1.0
            # Technical tokens carry weight: E17, 24VDC, NSK6203 must match exactly.
            if any(ch.isdigit() for ch in w) and any(ch.isalpha() for ch in w):
                vec[(h >> 7) % self.dim] += 2.0
        padded = f"  {low} "
        for i in range(len(padded) - 2):
            tri = padded[i:i + 3]
            h = int.from_bytes(hashlib.blake2b(tri.encode(), digest_size=8).digest(), "little")
            vec[h % self.dim] += 0.35
        for i, v in enumerate(vec):
            if v:
                vec[i] = 1.0 + math.log(v)
        n = float(np.linalg.norm(vec))
        if n > 0:
            vec /= n
        return [round(float(v), 6) for v in vec]

    async def embed(self, texts: Sequence[str]) -> List[List[float]]:
        self.require_ready()
        return [self._vector(t) for t in texts]

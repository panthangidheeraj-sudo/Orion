"""Main reasoning VLM adapters (§3) — Qwen3-VL-2B-Instruct and friends.

Two real local paths, both selected only when they are genuinely present:

``QwenVLGenAIProvider``
    ``onnxruntime-genai`` with a multimodal Qwen3-VL export under
    ``data/models/<model_id>/``.  This is the path that reaches the Snapdragon
    NPU on Windows through the QNN execution provider.

``LocalOpenAICompatProvider``
    An OpenAI-shaped server running on **this machine** (llama.cpp, Ollama,
    LM Studio).  The base URL is checked against the loopback interface and a
    non-local host is refused outright, because §24 forbids sending camera
    frames or documents off the device by default.

Neither is hard-wired: §3 says "Do not hard-wire one model."  ``model_id`` is
configuration, and swapping to Qwen3-VL-4B/8B, Intern3.5-VL or Gemma-4-E4B is
a settings change, not a code change.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence
from urllib.parse import urlparse

from app.config import settings
from app.errors import ModelUnavailable
from app.logging_setup import get_logger
from app.models.base import READY, ImageRef, ModelHealth, ReasoningProvider
from app.models.runtime import model_dir, runtime_info

log = get_logger(__name__)

FALLBACK = "heuristic-offline reasoner"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}

_TOOL_BLOCK = re.compile(
    r"```(?:tool_call|json)?\s*(\{.*?\})\s*```|<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.S,
)


def parse_tool_calls(text: str) -> tuple[str, List[Dict[str, Any]]]:
    """Pull tool-call objects out of a model's free-form answer.

    Accepts ```tool_call {...}``` or <tool_call>{...}</tool_call>.  Anything
    that is not valid JSON with a ``tool``/``name`` key is left in the prose,
    so a model talking *about* JSON does not accidentally trigger a tool.
    """
    calls: List[Dict[str, Any]] = []

    def _take(match: re.Match) -> str:
        blob = match.group(1) or match.group(2) or ""
        try:
            obj = json.loads(blob)
        except Exception:
            return match.group(0)
        name = obj.get("tool") or obj.get("name")
        if not isinstance(name, str):
            return match.group(0)
        args = obj.get("arguments") or obj.get("args") or obj.get("parameters") or {}
        calls.append({"tool": name, "arguments": args if isinstance(args, dict) else {}})
        return ""

    cleaned = _TOOL_BLOCK.sub(_take, text or "").strip()
    return cleaned, calls


def _image_data_url(ref: ImageRef) -> str:
    data = Path(ref.path).read_bytes()
    return f"data:{ref.mime_type};base64," + base64.b64encode(data).decode("ascii")


class QwenVLGenAIProvider(ReasoningProvider):
    """onnxruntime-genai multimodal path."""

    def __init__(self, model_id: Optional[str] = None, max_new_tokens: int = 768) -> None:
        super().__init__(model_id or settings.reasoning_model_id, "onnxruntime-genai")
        self.max_new_tokens = max_new_tokens
        self._model = None
        self._processor = None
        self._tokenizer = None
        self._og = None

    def _load(self) -> None:
        root = model_dir(self.model_id)
        if not root.exists() or not any(root.rglob("*.onnx")):
            raise ModelUnavailable(
                f"no exported model under data/models/{self.model_id}/",
                model=self.model_id, fallback=FALLBACK,
            )
        try:
            import onnxruntime_genai as og  # type: ignore
        except Exception as exc:
            raise ModelUnavailable(
                f"onnxruntime-genai not importable ({type(exc).__name__}); install "
                "onnxruntime-genai (or the QNN build on a Snapdragon host)",
                model=self.model_id, fallback=FALLBACK,
            )
        self._og = og
        self._model = og.Model(str(root))
        self._tokenizer = og.Tokenizer(self._model)
        try:
            self._processor = self._model.create_multimodal_processor()
        except Exception:
            self._processor = None  # text-only export

        info = runtime_info()
        # onnxruntime-genai does not expose per-session providers, so the NPU
        # claim rests on the config the export carries plus what this ORT build
        # actually has.  If either is missing we report CPU. §4.
        cfg_text = ""
        cfg = root / "genai_config.json"
        if cfg.exists():
            cfg_text = cfg.read_text(encoding="utf-8", errors="ignore")
        uses_qnn = "QNN" in cfg_text or "qnn" in cfg_text
        npu = bool(uses_qnn and info.qnn_available)
        self._health = ModelHealth(
            role=self.role, provider=self.provider, model_id=self.model_id, status=READY,
            runtime="onnxruntime-genai",
            accelerator="npu" if npu else "cpu", npu=npu,
            asset_path=str(root),
            detail={
                "multimodal": self._processor is not None,
                "genai_config_declares_qnn": uses_qnn,
                "ort_has_qnn_ep": info.qnn_available,
                "max_new_tokens": self.max_new_tokens,
            },
        )

    def supports_streaming(self) -> bool:
        return True

    def capabilities(self) -> Dict[str, Any]:
        return {**super().capabilities(), "streaming": True,
                "images": self._processor is not None, "tool_calls": "prompted"}

    def _prompt(self, messages: Sequence[Dict[str, Any]]) -> str:
        parts: List[str] = []
        for m in messages:
            role = m.get("role", "user")
            parts.append(f"<|im_start|>{role}\n{m.get('content','')}<|im_end|>")
        parts.append("<|im_start|>assistant\n")
        return "\n".join(parts)

    async def generate(self, messages, images=None, tools=None, context=None) -> Dict[str, Any]:
        self.require_ready(fallback=FALLBACK)
        chunks: List[str] = []
        async for ev in self.stream(messages, images=images, tools=tools, context=context):
            if ev["type"] == "text":
                chunks.append(ev["value"])
        text, calls = parse_tool_calls("".join(chunks))
        return {"text": text, "tool_calls": calls, "model": self.model_id,
                "usage": {"output_chars": len("".join(chunks))}}

    async def stream(self, messages, images=None, tools=None, context=None) -> AsyncIterator[Dict[str, Any]]:
        self.require_ready(fallback=FALLBACK)
        og = self._og
        prompt = self._prompt(messages)
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _worker() -> None:
            try:
                if images and self._processor is not None:
                    pil = og.Images.open(*[str(i.path) for i in images])
                    inputs = self._processor(prompt, images=pil)
                else:
                    inputs = {"input_ids": self._tokenizer.encode(prompt)}
                params = og.GeneratorParams(self._model)
                params.set_search_options(max_length=self.max_new_tokens, do_sample=False)
                generator = og.Generator(self._model, params)
                if hasattr(generator, "set_inputs"):
                    generator.set_inputs(inputs)
                stream = self._tokenizer.create_stream()
                while not generator.is_done():
                    generator.generate_next_token()
                    token = generator.get_next_tokens()[0]
                    loop.call_soon_threadsafe(queue.put_nowait,
                                              {"type": "text", "value": stream.decode(token)})
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "value": str(exc)})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "eos", "value": ""})

        asyncio.get_running_loop().run_in_executor(None, _worker)
        buf: List[str] = []
        while True:
            ev = await queue.get()
            if ev["type"] == "eos":
                break
            if ev["type"] == "error":
                raise ModelUnavailable(ev["value"], model=self.model_id, fallback=FALLBACK)
            buf.append(ev["value"])
            yield ev
        text, calls = parse_tool_calls("".join(buf))
        yield {"type": "done", "value": {"text": text, "tool_calls": calls,
                                         "model": self.model_id}}


class LocalOpenAICompatProvider(ReasoningProvider):
    """OpenAI-shaped local server. Loopback only — a remote host is refused."""

    def __init__(self, base_url: str = "http://127.0.0.1:11434/v1",
                 model_id: Optional[str] = None, timeout_s: float = 120.0) -> None:
        super().__init__(model_id or settings.reasoning_model_id, "local-openai-compat")
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def _load(self) -> None:
        host = (urlparse(self.base_url).hostname or "").lower()
        if host not in LOOPBACK_HOSTS:
            raise ModelUnavailable(
                f"refusing non-loopback reasoning endpoint '{host}': local-first "
                "operation forbids sending frames or documents off the device",
                model=self.model_id, fallback=FALLBACK,
            )
        import httpx

        try:
            r = httpx.get(f"{self.base_url}/models", timeout=3.0)
            r.raise_for_status()
            served = [m.get("id") for m in (r.json().get("data") or [])]
        except Exception as exc:
            raise ModelUnavailable(
                f"no local server at {self.base_url} ({type(exc).__name__})",
                model=self.model_id, fallback=FALLBACK,
            )
        self._health = ModelHealth(
            role=self.role, provider=self.provider, model_id=self.model_id, status=READY,
            runtime="local-http", accelerator="unknown", npu=False,
            detail={"base_url": self.base_url, "served_models": served[:12],
                    "note": "Accelerator is whatever that server uses; this process "
                            "cannot verify NPU involvement, so it claims none."},
        )

    def supports_streaming(self) -> bool:
        return True

    def _payload(self, messages, images, tools, stream: bool) -> Dict[str, Any]:
        msgs = [dict(m) for m in messages]
        if images:
            content: List[Dict[str, Any]] = [{"type": "text", "text": msgs[-1].get("content", "")}]
            for ref in images[:4]:
                content.append({"type": "image_url",
                                "image_url": {"url": _image_data_url(ref)}})
            msgs[-1] = {"role": msgs[-1].get("role", "user"), "content": content}
        body: Dict[str, Any] = {"model": self.model_id, "messages": msgs,
                                "temperature": 0.2, "stream": stream}
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        return body

    async def generate(self, messages, images=None, tools=None, context=None) -> Dict[str, Any]:
        self.require_ready(fallback=FALLBACK)
        import httpx

        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(f"{self.base_url}/chat/completions",
                                  json=self._payload(messages, images, tools, False))
            r.raise_for_status()
            data = r.json()
        choice = (data.get("choices") or [{}])[0].get("message", {}) or {}
        text, calls = parse_tool_calls(choice.get("content") or "")
        for tc in choice.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            calls.append({"tool": fn.get("name"), "arguments": args})
        return {"text": text, "tool_calls": [c for c in calls if c.get("tool")],
                "model": self.model_id, "usage": data.get("usage", {})}

    async def stream(self, messages, images=None, tools=None, context=None) -> AsyncIterator[Dict[str, Any]]:
        self.require_ready(fallback=FALLBACK)
        import httpx

        buf: List[str] = []
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            async with client.stream("POST", f"{self.base_url}/chat/completions",
                                     json=self._payload(messages, images, tools, True)) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    blob = line[5:].strip()
                    if blob == "[DONE]":
                        break
                    try:
                        delta = json.loads(blob)["choices"][0]["delta"].get("content")
                    except Exception:
                        continue
                    if delta:
                        buf.append(delta)
                        yield {"type": "text", "value": delta}
        text, calls = parse_tool_calls("".join(buf))
        yield {"type": "done", "value": {"text": text, "tool_calls": calls,
                                         "model": self.model_id}}

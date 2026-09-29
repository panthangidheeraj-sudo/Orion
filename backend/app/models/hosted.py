"""Groq-hosted reasoning model through Groq's OpenAI-compatible API.

This is the reasoning provider for a deployment that is *not* a Snapdragon
machine — the Render demo for judges (``VF_REASONING_PROVIDER=hosted-groq``). It
is a different model from the on-device path (Qwen3-VL-4B-Instruct on the
Snapdragon NPU through GenieX/QAIRT, which this module never touches), and the
status report says so plainly:

* ``provider="hosted-groq"``, ``hosted=True``, ``npu=False``,
  ``accelerator="remote"``. The provider's hardware is theirs, not something
  this process can observe, so it never claims a Snapdragon/Qualcomm NPU —
  ``ModelHealth.to_dict`` forces ``npu`` off for any hosted adapter regardless
  of what an adapter sets.
* Used only when an API key is configured (``GROQ_API_KEY`` or
  ``VF_HOSTED_LLM_API_KEY``). The key is read from the server's environment and
  is sent only as the ``Authorization`` header of requests to the configured
  base URL; it is never returned by an API, logged, or written into an error
  message.
* READY means a real request succeeded: the provider's ``/models`` list shows
  the configured model (or, if the provider has no such route, a 1-token
  completion works). A wrong key, exhausted quota, an unreachable host or a
  model the provider does not serve leaves the role UNAVAILABLE with that
  reason — there is no stand-in model.

Photos and camera frames for a turn are sent to the provider (downscaled JPEG,
data URL, at most three per request) because a hosted model can only see what
it is sent. Model files, SQLite databases and GenieX bundles are never
uploaded — nothing in this module reads them.
"""

from __future__ import annotations

import base64
import io
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence

from app.config import settings
from app.errors import ModelUnavailable
from app.logging_setup import get_logger
from app.models.base import READY, ImageRef, ModelHealth
from app.models.qwen_vl import LocalOpenAICompatProvider, parse_tool_calls

log = get_logger(__name__)

PROVIDER = "hosted-groq"
FALLBACK = "none — Orion will say the hosted AI is unavailable rather than answer without a model"
MAX_IMAGE_SIDE = 1280
MAX_IMAGES = 3  # Groq accepts at most 3 images per request

def configured() -> bool:
    return bool(settings.hosted_llm_api_key.strip() and settings.hosted_llm_base_url.strip())


def _data_url(ref: ImageRef) -> str:
    """The image as a downscaled JPEG data URL (a hosted API has request-size limits)."""
    from PIL import Image  # pillow is a core dependency

    with Image.open(ref.path) as im:
        im = im.convert("RGB")
        im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


class HostedGroqProvider(LocalOpenAICompatProvider):
    """Reuses the OpenAI-compatible request/response handling of the local
    adapter, with a remote base URL, a server-side key and honest reporting."""

    def __init__(self) -> None:
        super().__init__(base_url=settings.hosted_llm_base_url,
                         model_id=settings.hosted_llm_model, timeout_s=settings.hosted_llm_timeout_s)
        self.provider = PROVIDER
        self._health.provider = PROVIDER
        self._key = settings.hosted_llm_api_key.strip()

    # ------------------------------------------------------------ plumbing
    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._key}"}

    @staticmethod
    def _http_reason(code: int) -> str:
        if code in (401, 403):
            return f"the hosted AI provider rejected the API key (HTTP {code})"
        if code == 429:
            return "the hosted AI provider is rate-limiting or the quota is used up (HTTP 429)"
        if code >= 500:
            return f"the hosted AI provider is unavailable (HTTP {code})"
        return f"the hosted AI provider answered HTTP {code}"

    def _unavailable(self, reason: str) -> ModelUnavailable:
        return ModelUnavailable(reason.replace(self._key, "***") if self._key else reason,
                                model=self.model_id, fallback=FALLBACK)

    def _client(self, timeout: Optional[float] = None):
        import httpx
        return httpx.AsyncClient(timeout=timeout or self.timeout_s, headers=self._headers())

    def _payload(self, messages, images, tools, stream, context=None) -> Dict[str, Any]:
        msgs = [dict(m) for m in messages]
        body = super()._payload(msgs, None, tools, stream, context)
        if images:
            last = body["messages"][-1]
            content: List[Dict[str, Any]] = [{"type": "text", "text": str(last.get("content", ""))}]
            for ref in list(images)[:MAX_IMAGES]:
                content.append({"type": "image_url", "image_url": {"url": _data_url(ref)}})
            body["messages"][-1] = {"role": last.get("role", "user"), "content": content}
        # Groq's Qwen model can "think" before answering. Ask for the final answer
        # only (never the reasoning text), so the router still gets a clean JSON
        # object and the technician never sees chain-of-thought. Empty = leave unset.
        if settings.hosted_llm_reasoning_effort:
            body["reasoning_effort"] = settings.hosted_llm_reasoning_effort
        if settings.hosted_llm_reasoning_format:
            body["reasoning_format"] = settings.hosted_llm_reasoning_format
        return body

    # ---------------------------------------------------------------- load
    def _load(self) -> None:
        import httpx

        if not configured():
            raise self._unavailable(
                "hosted AI is not configured (set GROQ_API_KEY or VF_HOSTED_LLM_API_KEY)")
        if not settings.hosted_llm_model.strip():
            raise self._unavailable("VF_HOSTED_LLM_MODEL is empty")
        if not self.base_url.lower().startswith("https://"):
            raise self._unavailable("the hosted AI endpoint must use https://")

        served: List[str] = []
        try:
            r = httpx.get(f"{self.base_url}/models", headers=self._headers(), timeout=8.0)
            if r.status_code in (401, 403, 429) or r.status_code >= 500:
                raise self._unavailable(self._http_reason(r.status_code))
            if r.status_code < 400:
                served = [m.get("id") for m in (r.json().get("data") or []) if m.get("id")]
            elif r.status_code not in (404, 405):
                raise self._unavailable(self._http_reason(r.status_code))
        except ModelUnavailable:
            raise
        except Exception as exc:
            raise self._unavailable(f"cannot reach the hosted AI provider ({type(exc).__name__})")

        if served and not any(s.lower() == self.model_id.lower() for s in served):
            raise self._unavailable(
                f"the provider does not list '{self.model_id}' for this key")
        if not served:
            # No usable model list: prove the model answers with a real 1-token call.
            try:
                r = httpx.post(f"{self.base_url}/chat/completions", headers=self._headers(),
                               timeout=30.0,
                               json={"model": self.model_id, "max_tokens": 1, "temperature": 0,
                                     "messages": [{"role": "user", "content": "ok"}]})
            except Exception as exc:
                raise self._unavailable(f"hosted AI probe failed ({type(exc).__name__})")
            if r.status_code >= 400:
                raise self._unavailable(self._http_reason(r.status_code))

        self._health = ModelHealth(
            role=self.role, provider=PROVIDER, model_id=self.model_id, status=READY,
            runtime="hosted-openai-api", accelerator="remote", npu=False, synthetic=False,
            hosted=True,
            detail={"images": True, "streaming": True,
                    "note": "Runs on the inference provider's hardware, not on this device "
                            "and not on a Snapdragon NPU. Photos and camera frames for a turn "
                            "are sent to the provider."},
        )

    def capabilities(self) -> Dict[str, Any]:
        return {"role": self.role, "provider": PROVIDER, "model_id": self.model_id,
                "streaming": True, "images": True, "tool_calls": "prompted", "hosted": True}

    # ------------------------------------------------------- request paths
    async def generate(self, messages, images=None, tools=None, context=None) -> Dict[str, Any]:
        import httpx

        self.require_ready(fallback=FALLBACK)
        async with self._client() as client:
            body = self._payload(messages, images, tools, False, context)
            try:
                r = await client.post(f"{self.base_url}/chat/completions", json=body)
                if r.status_code == 400:
                    # A model/version that rejects an optional parameter: ask again
                    # without them. The caller still validates the output strictly.
                    lean = {k: v for k, v in body.items()
                            if k not in ("response_format", "reasoning_effort", "reasoning_format")}
                    if lean != body:
                        r = await client.post(f"{self.base_url}/chat/completions", json=lean)
                r.raise_for_status()
                data = r.json()
            except httpx.HTTPStatusError as exc:
                raise self._unavailable(self._http_reason(exc.response.status_code))
            except httpx.HTTPError as exc:
                raise self._unavailable(f"hosted AI request failed ({type(exc).__name__})")
        choice = (data.get("choices") or [{}])[0].get("message", {}) or {}
        text, calls = parse_tool_calls(choice.get("content") or "")
        return {"text": text, "tool_calls": calls, "model": self.model_id,
                "usage": data.get("usage", {})}

    async def stream(self, messages, images=None, tools=None, context=None) -> AsyncIterator[Dict[str, Any]]:
        import httpx
        import json

        self.require_ready(fallback=FALLBACK)
        buf: List[str] = []
        try:
            async with self._client() as client:
                async with client.stream("POST", f"{self.base_url}/chat/completions",
                                         json=self._payload(messages, images, tools, True, context)) as resp:
                    if resp.status_code >= 400:
                        raise self._unavailable(self._http_reason(resp.status_code))
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
        except httpx.HTTPError as exc:
            raise self._unavailable(f"hosted AI stream failed ({type(exc).__name__})")
        text, calls = parse_tool_calls("".join(buf))
        yield {"type": "done", "value": {"text": text, "tool_calls": calls, "model": self.model_id}}

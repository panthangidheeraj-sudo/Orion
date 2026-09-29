"""Remote vision adapters — the API side of the Render ``orion-vision`` service.

On Render, Orion runs as a public API plus a private vision service. These
adapters let the API use the vision service through the same interfaces the
in-process adapters implement, so the agent and the tools do not change.

Honesty rules (the same as every other adapter):

- A role is READY only when the vision service *itself* reported that role as
  ``ready`` in a status response that is at most ``vision_status_ttl_s`` old.
  Configuration alone never makes a role ready.
- Health is live. If the service goes away, the next ``health()`` says so, and
  it recovers on its own when the service comes back.
- Nothing here ever reports an NPU. The service runs on Render CPU, and
  ``hosted=True`` makes ``ModelHealth.to_dict`` force ``npu=False`` anyway.
- The service key is sent only as a request header to ``VF_VISION_URL``; it is
  never logged, never returned by a route, and never put in an error message.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.config import settings
from app.errors import ModelUnavailable
from app.logging_setup import get_logger
from app.models.base import (
    READY, UNAVAILABLE, ImageRef, ModelHealth, OCRProvider, VisionClassifier,
    VisionDetector, VisionSegmenter, VisionTracker,
)

log = get_logger(__name__)

PROVIDER = "remote-vision"
KEY_HEADER = "X-Orion-Internal-Key"
VISION_ROLES = ("detector", "classifier", "segmenter", "tracker", "ocr")


def configured() -> bool:
    return bool(settings.vision_url.strip())


def base_url() -> str:
    url = settings.vision_url.strip().rstrip("/")
    # Render's fromService hostport is "host:port" with no scheme. Private
    # traffic between services is plain HTTP inside Render's network.
    if url and "://" not in url:
        url = "http://" + url
    return url


def _headers() -> Dict[str, str]:
    return {KEY_HEADER: settings.internal_key, "Accept": "application/json"}


class VisionClient:
    """Cached, honest view of the vision service's status."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: Optional[Tuple[float, str, Dict[str, Any]]] = None

    def reset(self) -> None:
        with self._lock:
            self._cache = None

    def invalidate(self, reason: str) -> None:
        """A call just failed: stop trusting the last READY answer."""
        with self._lock:
            self._cache = (time.monotonic(), base_url(),
                           {"reachable": False, "reason": reason, "roles": {}})

    def status(self) -> Dict[str, Any]:
        """{"reachable": bool, "reason": str|None, "roles": {role: health dict}}."""
        if not configured():
            return {"reachable": False, "reason": "VF_VISION_URL is not set", "roles": {}}
        if not settings.internal_key:
            return {"reachable": False, "reason": "VF_INTERNAL_KEY is not set", "roles": {}}
        url = base_url()
        ttl = settings.vision_status_ttl_s
        with self._lock:
            if self._cache and self._cache[1] == url and time.monotonic() - self._cache[0] < (
                    ttl if self._cache[2].get("reachable") else min(ttl, 5.0)):
                return self._cache[2]
        result = self._fetch(url)
        with self._lock:
            self._cache = (time.monotonic(), url, result)
        return result

    @staticmethod
    def _fetch(url: str) -> Dict[str, Any]:
        import httpx

        try:
            r = httpx.get(f"{url}/internal/status", headers=_headers(), timeout=3.0)
        except httpx.HTTPError as exc:
            return {"reachable": False, "roles": {},
                    "reason": f"vision service unreachable ({type(exc).__name__})"}
        if r.status_code in (401, 403):
            return {"reachable": False, "roles": {},
                    "reason": "vision service rejected the internal key (check VF_INTERNAL_KEY)"}
        if r.status_code != 200:
            return {"reachable": False, "roles": {},
                    "reason": f"vision service answered HTTP {r.status_code}"}
        try:
            roles = r.json().get("roles") or {}
        except ValueError:
            return {"reachable": False, "roles": {}, "reason": "vision service sent invalid JSON"}
        return {"reachable": True, "reason": None, "roles": roles}

    def summary(self) -> Dict[str, Any]:
        """Safe for the public status route: no URL, no key."""
        if not configured():
            return {"configured": False, "status": "not_configured", "reachable": False,
                    "ready_roles": [], "reason": "no vision service configured"}
        st = self.status()
        ready = [r for r in VISION_ROLES if (st["roles"].get(r) or {}).get("status") == READY]
        if not st["reachable"]:
            status = UNAVAILABLE
        else:
            status = "ready" if len(ready) == len(VISION_ROLES) else (
                "partial" if ready else UNAVAILABLE)
        return {"configured": True, "status": status, "reachable": st["reachable"],
                "ready_roles": ready, "reason": st["reason"]}

    async def call(self, role: str, path: str, image: ImageRef,
                   meta: Optional[Dict[str, Any]], model_id: str) -> Dict[str, Any]:
        import httpx

        try:
            data = Path(image.path).read_bytes()
        except OSError as exc:
            raise ModelUnavailable(f"image could not be read ({type(exc).__name__})",
                                   model=model_id, role=role, provider=PROVIDER)
        files = {"image": (image.id or "image", data, image.mime_type or "application/octet-stream")}
        form = {"meta": json.dumps(meta or {})}
        try:
            async with httpx.AsyncClient(timeout=settings.vision_timeout_s) as c:
                r = await c.post(f"{base_url()}{path}", headers=_headers(), files=files, data=form)
        except httpx.HTTPError as exc:
            self.invalidate(f"vision service unreachable ({type(exc).__name__})")
            raise ModelUnavailable(f"vision service unreachable ({type(exc).__name__})",
                                   model=model_id, role=role, provider=PROVIDER)
        if r.status_code in (401, 403):
            self.invalidate("vision service rejected the internal key")
            raise ModelUnavailable("vision service rejected the internal key",
                                   model=model_id, role=role, provider=PROVIDER)
        if r.status_code != 200:
            reason = f"vision service answered HTTP {r.status_code}"
            try:
                reason = str(r.json().get("reason") or reason)[:300]
            except ValueError:
                pass
            if r.status_code >= 500:
                self.invalidate(reason)
            raise ModelUnavailable(reason, model=model_id, role=role, provider=PROVIDER)
        try:
            return r.json()
        except ValueError:
            raise ModelUnavailable("vision service sent invalid JSON",
                                   model=model_id, role=role, provider=PROVIDER)


client = VisionClient()


class _RemoteMixin:
    """Live-health behaviour shared by the five remote roles."""

    role: str
    ROUTE = ""

    def _init_remote(self, model_id: str) -> None:
        self._health = ModelHealth(role=self.role, provider=PROVIDER, model_id=model_id,
                                   hosted=True)
        self._loaded = True  # health() below is always live

    def health(self) -> ModelHealth:
        st = client.status()
        entry = (st["roles"] or {}).get(self.role) or {}
        if st["reachable"] and entry.get("status") == READY:
            self.model_id = entry.get("model_id") or self.model_id
            self._health = ModelHealth(
                role=self.role, provider=PROVIDER, model_id=self.model_id, status=READY,
                runtime=entry.get("runtime") or "remote", accelerator=entry.get("accelerator") or "cpu",
                npu=False, synthetic=bool(entry.get("synthetic")), hosted=True,
                load_ms=entry.get("load_ms"),
                detail={"service": "orion-vision", "remote_provider": entry.get("provider")})
        else:
            if not st["reachable"]:
                reason = st["reason"]
            else:
                reason = entry.get("reason") or "the vision service reports this role is not ready"
            self._health = ModelHealth(
                role=self.role, provider=PROVIDER, model_id=self.model_id, status=UNAVAILABLE,
                runtime="remote", accelerator="none", npu=False, hosted=True, reason=reason,
                detail={"service": "orion-vision"})
        return self._health

    def capabilities(self) -> Dict[str, Any]:
        return {"role": self.role, "provider": PROVIDER, "model_id": self.model_id,
                "remote": True, "service": "orion-vision"}

    async def _post(self, image: ImageRef, meta: Optional[Dict[str, Any]] = None) -> Any:
        self.require_ready()  # type: ignore[attr-defined]
        body = await client.call(self.role, self.ROUTE, image, meta, self.model_id)
        return body


class RemoteDetector(_RemoteMixin, VisionDetector):
    ROUTE = "/internal/detect"

    def __init__(self, model_id: Optional[str] = None) -> None:
        VisionDetector.__init__(self, model_id or settings.detector_model_id, PROVIDER)
        self._init_remote(self.model_id)

    async def detect(self, image: ImageRef) -> List[Dict[str, Any]]:
        return (await self._post(image)).get("result") or []


class RemoteClassifier(_RemoteMixin, VisionClassifier):
    ROUTE = "/internal/classify"

    def __init__(self, model_id: Optional[str] = None) -> None:
        VisionClassifier.__init__(self, model_id or settings.classifier_model_id, PROVIDER)
        self._init_remote(self.model_id)

    async def classify(self, image: ImageRef, bbox: Optional[Sequence[float]] = None):
        return (await self._post(image, {"bbox": list(bbox) if bbox else None})).get("result") or []


class RemoteSegmenter(_RemoteMixin, VisionSegmenter):
    ROUTE = "/internal/segment"

    def __init__(self, model_id: Optional[str] = None) -> None:
        VisionSegmenter.__init__(self, model_id or settings.segmenter_model_id, PROVIDER)
        self._init_remote(self.model_id)

    async def segment(self, image: ImageRef, target: Optional[str] = None) -> Dict[str, Any]:
        return (await self._post(image, {"target": target})).get("result") or {}


class RemoteTracker(_RemoteMixin, VisionTracker):
    ROUTE = "/internal/track"

    def __init__(self, model_id: Optional[str] = None) -> None:
        VisionTracker.__init__(self, model_id or settings.tracker_model_id, PROVIDER)
        self._init_remote(self.model_id)

    async def track(self, frame: ImageRef, state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return (await self._post(frame, {"state": state or {}})).get("result") or {}


class RemoteOCR(_RemoteMixin, OCRProvider):
    ROUTE = "/internal/ocr"

    def __init__(self, model_id: Optional[str] = None) -> None:
        OCRProvider.__init__(self, model_id or settings.ocr_model_id, PROVIDER)
        self._init_remote(self.model_id)

    async def extract(self, image: ImageRef) -> List[Dict[str, Any]]:
        return (await self._post(image)).get("result") or []

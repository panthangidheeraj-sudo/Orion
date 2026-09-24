"""Optional web research (§16).

Off by default.  Priority order is fixed by the specification: current job
context, then user documents, then local memory/RAG, and only then the web.
The orchestrator enforces that order; this module only provides the provider.

Results always carry title, URL, snippet, domain and retrieval time so a final
answer can cite web evidence.
"""

from __future__ import annotations

import abc
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.config import settings
from app.errors import VFError
from app.logging_setup import get_logger
from app.util import preview

log = get_logger(__name__)

BLOCKED_SCHEMES = {"file", "ftp", "data", "javascript"}


class SearchResult(dict):
    """title / url / snippet / domain / retrieved_at."""


class WebSearchProvider(abc.ABC):
    name = "none"
    enabled = False

    @abc.abstractmethod
    async def search(self, query: str) -> List[SearchResult]:
        ...

    async def fetch(self, url: str) -> Dict[str, Any]:
        raise VFError("this provider cannot fetch pages", provider=self.name)

    def status(self) -> Dict[str, Any]:
        return {"provider": self.name, "enabled": self.enabled}


class DisabledSearch(WebSearchProvider):
    name = "disabled"
    enabled = False

    async def search(self, query: str) -> List[SearchResult]:
        log.info("web search requested but disabled: %s", preview(query, 60))
        return []

    def status(self) -> Dict[str, Any]:
        return {"provider": "disabled", "enabled": False,
                "reason": "VF_WEB_SEARCH_ENABLED is false — local-first default (§16/§24)"}


class HttpJsonSearch(WebSearchProvider):
    """Generic JSON search endpoint.

    The endpoint and key come from the environment only; §24 forbids keys in
    source.  The response is mapped defensively because every vendor's JSON
    differs slightly.
    """

    name = "http-json"

    def __init__(self) -> None:
        self.endpoint = settings.web_search_endpoint
        self.api_key = settings.web_search_api_key
        self.enabled = bool(settings.web_search_enabled and self.endpoint)

    async def search(self, query: str) -> List[SearchResult]:
        if not self.enabled:
            return []
        import httpx

        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                r = await client.get(self.endpoint,
                                     params={"q": query,
                                             "count": settings.web_search_max_results},
                                     headers=headers)
                r.raise_for_status()
                payload = r.json()
        except Exception as exc:
            # §25: web unavailable means local RAG carries on.
            log.warning("web search failed (%s); continuing with local knowledge",
                        type(exc).__name__)
            return []

        items = (payload.get("results") or payload.get("web", {}).get("results")
                 or payload.get("items") or [])
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        out: List[SearchResult] = []
        for it in items[: settings.web_search_max_results]:
            url = it.get("url") or it.get("link") or ""
            scheme = (urlparse(url).scheme or "").lower()
            if scheme in BLOCKED_SCHEMES or not url:
                continue
            out.append(SearchResult({
                "title": it.get("title") or it.get("name") or url,
                "url": url,
                "snippet": preview(it.get("snippet") or it.get("description") or "", 400),
                "domain": urlparse(url).netloc,
                "retrieved_at": now,
                "source": "web",
            }))
        return out

    def status(self) -> Dict[str, Any]:
        return {"provider": self.name, "enabled": self.enabled,
                "endpoint_configured": bool(self.endpoint),
                "key_configured": bool(self.api_key)}


_provider: Optional[WebSearchProvider] = None


def get_provider() -> WebSearchProvider:
    global _provider
    if _provider is None:
        if settings.web_search_enabled and settings.web_search_provider == "http-json":
            _provider = HttpJsonSearch()
        else:
            _provider = DisabledSearch()
    return _provider


def reset_provider() -> None:
    global _provider
    _provider = None

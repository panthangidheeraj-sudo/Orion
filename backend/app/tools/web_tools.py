"""Web tools (§16).

Optional and off by default.  The orchestrator only offers these when the
technician has enabled web research for the turn, and the answer cites what
came back.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import urlparse

from app.agent.tool_registry import registry as tools
from app.config import settings
from app.knowledge import web_search as ws
from app.logging_setup import get_logger
from app.util import preview

log = get_logger(__name__)
BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "169.254.169.254"}


@tools.tool(
    "web_search",
    "Search the web for current manufacturer documentation, specifications or "
    "service information that is not in the local documents. Use only after "
    "local job context, documents and memory have been checked.",
    {"type": "object", "additionalProperties": False,
     "required": ["query"],
     "properties": {"query": {"type": "string", "minLength": 3, "maxLength": 300}}},
    category="web", online=True)
async def web_search(query: str):
    provider = ws.get_provider()
    if not provider.enabled:
        return {"results": [], "count": 0, "degraded": True,
                "reason": "web research is turned off; local documents and memory are "
                          "being used instead",
                "provider": provider.status(), "source": "web"}
    results = await provider.search(query)
    return {"results": results, "count": len(results), "query": query,
            "provider": provider.name, "source": "web"}


@tools.tool(
    "fetch_web_source",
    "Fetch a specific public web page that a search result pointed at, so its "
    "content can be quoted and cited.",
    {"type": "object", "additionalProperties": False,
     "required": ["url"],
     "properties": {"url": {"type": "string", "minLength": 8, "maxLength": 600}}},
    category="web", online=True)
async def fetch_web_source(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {"fetched": False, "reason": "only http and https URLs are fetched", "url": url}
    host = (parsed.hostname or "").lower()
    # A fetch tool must not be usable to reach the machine it runs on.
    if host in BLOCKED_HOSTS or host.endswith(".local") or host.startswith("192.168.") \
            or host.startswith("10.") or host.startswith("172.16."):
        return {"fetched": False, "reason": "refusing to fetch a local or private address",
                "url": url}
    if not settings.web_search_enabled:
        return {"fetched": False, "reason": "web research is turned off", "url": url}

    import httpx

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True,
                                     max_redirects=3) as client:
            r = await client.get(url, headers={"Accept": "text/html,text/plain"})
            r.raise_for_status()
            body = r.text[:120_000]
    except Exception as exc:
        log.warning("fetch failed for %s: %s", parsed.netloc, type(exc).__name__)
        return {"fetched": False, "reason": f"fetch failed ({type(exc).__name__})", "url": url}

    import re

    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", body, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join(text.split())
    return {"fetched": True, "url": url, "domain": parsed.netloc,
            "title": preview(body.split("<title>")[-1].split("</title>")[0], 120)
            if "<title>" in body else parsed.netloc,
            "text": text[:8000], "source": "web"}

"""Web tools (§16).

Optional and off by default.  The orchestrator only offers these when the
technician has enabled web research for the turn, and the answer cites what
came back.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any, Dict, Optional
from urllib.parse import urljoin, urlparse

from app.agent.tool_registry import registry as tools
from app.config import settings
from app.knowledge import web_search as ws
from app.logging_setup import get_logger
from app.util import preview

log = get_logger(__name__)
BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "169.254.169.254",
                 "metadata.google.internal", "metadata"}
MAX_FETCH_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3


def _ip_is_public(ip: ipaddress._BaseAddress) -> bool:
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return ip.is_global and not ip.is_multicast


async def _refuse_reason(url: str) -> Optional[str]:
    """Why this URL must not be fetched, or None if it may be.

    The old check compared the hostname as a string, which let through
    172.17–172.31.x, 100.64/10, IPv6 private ranges, decimal/hex IP spellings,
    any DNS name that resolves to a private address, and — because redirects
    were followed automatically — any public URL that redirects inward.
    Now every hop is resolved and every address it resolves to must be a
    public, routable one.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "only http and https URLs are fetched"
    if parsed.username or parsed.password:
        return "URLs with embedded credentials are not fetched"
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return "the URL has no host"
    if host in BLOCKED_HOSTS or host.endswith((".local", ".internal", ".localhost")):
        return "refusing to fetch a local or private address"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        return "the host name does not resolve"
    if not infos:
        return "the host name does not resolve"
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            return "the host resolved to an unusable address"
        if not _ip_is_public(ip):
            return "refusing to fetch a local or private address"
    return None


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
    reason = await _refuse_reason(url)
    if reason:
        return {"fetched": False, "reason": reason, "url": url}
    if not settings.web_search_enabled:
        return {"fetched": False, "reason": "web research is turned off", "url": url}

    import httpx

    current = url
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            for _hop in range(MAX_REDIRECTS + 1):
                reason = await _refuse_reason(current)
                if reason:
                    return {"fetched": False, "reason": reason, "url": url}
                async with client.stream("GET", current,
                                         headers={"Accept": "text/html,text/plain"}) as r:
                    if r.is_redirect and "location" in r.headers:
                        current = urljoin(current, r.headers["location"])
                        continue
                    r.raise_for_status()
                    raw = bytearray()
                    async for chunk in r.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_FETCH_BYTES:
                            break
                    body = bytes(raw[:MAX_FETCH_BYTES]).decode(r.encoding or "utf-8",
                                                               errors="replace")[:120_000]
                    parsed = urlparse(current)
                    break
            else:
                return {"fetched": False, "reason": "too many redirects", "url": url}
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

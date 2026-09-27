"""Request-level protection: access key, rate limiting, security headers.

The backend was designed for 127.0.0.1, where the operating system is the
access control. Once it is deployed where the internet can reach it (Render,
a LAN address) that no longer holds, so these checks run on every request
before any route does:

- **Access key.** With ``VF_ACCESS_TOKEN`` set, every ``/api`` route needs the
  key, except the liveness/model-status probes (so the app can still say
  "backend online, locked") and the two media GETs the browser loads through
  ``<img>``/``<audio>`` tags, which cannot carry headers. Those are addressed
  by 100-bit random ids that are only discoverable through keyed routes.
- **Rate limiting.** A per-client sliding window, with a tighter budget for
  the routes that run models or accept uploads.
- **Headers.** nosniff, no framing, no referrer.
"""

from __future__ import annotations

import hmac
import re
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.logging_setup import get_logger

log = get_logger(__name__)

# Reachable without the key.
PUBLIC_EXACT = {"/", "/api/health", "/api/models/status"}
PUBLIC_PATTERNS = (
    re.compile(r"^/api/documents/[A-Za-z0-9_]{1,64}/pages/\d{1,5}$"),
    re.compile(r"^/api/voice/audio/[A-Za-z0-9_]{1,64}$"),
)

# Routes that run models, parse uploads or reload assets.
HEAVY_PATTERNS = (
    re.compile(r"^/api/chat(/stream)?$"),
    re.compile(r"^/api/documents/upload$"),
    re.compile(r"^/api/photo/"),
    re.compile(r"^/api/voice/(transcribe|synthesize)$"),
    re.compile(r"^/api/models/reload$"),
    re.compile(r"^/api/tools/call$"),
)


def max_body_bytes() -> int:
    from app.api._media import MAX_IMAGE_BYTES, MAX_PHOTOS_PER_TURN
    return max(settings.max_upload_bytes, MAX_IMAGE_BYTES * MAX_PHOTOS_PER_TURN) + (1 << 20)


def is_public(path: str, method: str) -> bool:
    if path in PUBLIC_EXACT:
        return True
    return method == "GET" and any(p.match(path) for p in PUBLIC_PATTERNS)


def presented_key(request: Request) -> str:
    key = request.headers.get("x-orion-key", "")
    if not key:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            key = auth[7:]
    return key.strip()


def key_ok(request: Request) -> bool:
    expected = settings.access_token
    if not expected:
        return True
    return hmac.compare_digest(presented_key(request).encode(), expected.encode())


def client_address(request: Request) -> str:
    if settings.trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"


class SlidingWindowLimiter:
    """In-memory, per-process limiter. Good enough for one Render instance;
    a multi-instance deployment would need a shared store."""

    def __init__(self, window_s: float = 60.0, max_keys: int = 20_000) -> None:
        self.window_s = window_s
        self.max_keys = max_keys
        self.hits: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)

    def allow(self, client: str, bucket: str, limit: int) -> Tuple[bool, int]:
        if limit <= 0:
            return True, 0
        now = time.monotonic()
        q = self.hits[(client, bucket)]
        while q and now - q[0] > self.window_s:
            q.popleft()
        if len(q) >= limit:
            retry = int(self.window_s - (now - q[0])) + 1
            return False, max(retry, 1)
        q.append(now)
        if len(self.hits) > self.max_keys:
            self._prune(now)
        return True, 0

    def _prune(self, now: float) -> None:
        for k in [k for k, q in self.hits.items() if not q or now - q[-1] > self.window_s]:
            del self.hits[k]


limiter = SlidingWindowLimiter()

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "cross-origin",
}


def _deny(status: int, code: str, reason: str, retry_after: Optional[int] = None) -> JSONResponse:
    headers = dict(SECURITY_HEADERS)
    if retry_after:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(status_code=status, content={"error": code, "reason": reason},
                        headers=headers)


async def guard(request: Request, call_next):
    """HTTP middleware: runs before routing, so a refused request never
    reaches a handler, a model or the database."""
    path = request.url.path
    method = request.method.upper()

    # CORS preflight carries no credentials by design; CORSMiddleware answers it.
    if method != "OPTIONS" and path.startswith("/api"):
        # Refuse a body that is obviously too large before it is read or
        # spooled to disk. (Chunked uploads are still capped while streaming.)
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > max_body_bytes():
            return _deny(413, "PAYLOAD_TOO_LARGE",
                         f"request body is larger than {max_body_bytes() // 1048576} MB")

        if not is_public(path, method) and not key_ok(request):
            return _deny(401, "UNAUTHORIZED",
                         "this backend needs an access key — add it in Profile → System status")

        client = client_address(request)
        heavy = any(p.match(path) for p in HEAVY_PATTERNS)
        ok, retry = limiter.allow(client, "all", settings.rate_limit_per_minute)
        if ok and heavy:
            ok, retry = limiter.allow(client, "heavy", settings.heavy_rate_limit_per_minute)
        if not ok:
            log.info("rate limited %s on %s", client, path)
            return _deny(429, "RATE_LIMITED", "too many requests — try again shortly", retry)

    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response


def startup_warnings() -> None:
    if not settings.access_token and settings.host not in ("127.0.0.1", "localhost", "::1"):
        log.warning(
            "VF_ACCESS_TOKEN is not set but the server listens on %s — anyone who can "
            "reach this port can read, change and delete every conversation, document "
            "and report. Set VF_ACCESS_TOKEN.", settings.host)
    if any(o.strip() == "*" for o in settings.cors_origins):
        log.warning("VF_CORS_ORIGINS contains '*': any website can call this backend "
                    "from a visitor's browser. List the frontend's origin instead.")

"""Logging that cannot leak document text, audio or camera frames.

Every record passes through a filter that truncates long messages and strips
anything that looks like a credential or a base64 media blob.  §24.
"""

from __future__ import annotations

import logging
import re
import sys

from app.config import settings

_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|authorization|bearer)\b\s*[:=]\s*\S+"
)
_DATA_URI = re.compile(r"data:[a-z]+/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]{24,}")
_LONG_B64 = re.compile(r"\b[A-Za-z0-9+/=]{256,}\b")
MAX_RECORD_CHARS = 600


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        clean = _SECRET.sub(r"\1=<redacted>", msg)
        clean = _DATA_URI.sub("<media:redacted>", clean)
        clean = _LONG_B64.sub("<blob:redacted>", clean)
        if len(clean) > MAX_RECORD_CHARS:
            clean = clean[:MAX_RECORD_CHARS] + "…<truncated>"
        if clean != msg:
            record.msg = clean
            record.args = ()
        return True


def configure_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_vf_configured", False):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)-28s %(message)s", "%H:%M:%S")
    )
    handler.addFilter(RedactingFilter())
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    root._vf_configured = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)

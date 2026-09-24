"""Structured error envelope shared by adapters, tools and the HTTP layer.

§25 fixes the shape:

    {"error": "MODEL_UNAVAILABLE", "model": "...", "reason": "...",
     "fallback": "configured fallback model"}
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class VFError(Exception):
    """Base class.  Carries a machine-readable code and a safe reason string."""

    code = "INTERNAL_ERROR"
    http_status = 500

    def __init__(self, reason: str, **extra: Any) -> None:
        super().__init__(reason)
        self.reason = reason
        self.extra: Dict[str, Any] = {k: v for k, v in extra.items() if v is not None}

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"error": self.code, "reason": self.reason}
        out.update(self.extra)
        return out


class ModelUnavailable(VFError):
    code = "MODEL_UNAVAILABLE"
    http_status = 503

    def __init__(self, reason: str, model: str, fallback: Optional[str] = None, **extra: Any):
        super().__init__(reason, model=model, fallback=fallback, **extra)


class ToolError(VFError):
    code = "TOOL_ERROR"
    http_status = 500

    def __init__(self, reason: str, tool: str, **extra: Any):
        super().__init__(reason, tool=tool, **extra)


class ToolNotAllowed(VFError):
    code = "TOOL_NOT_ALLOWED"
    http_status = 403


class ValidationFailed(VFError):
    code = "VALIDATION_FAILED"
    http_status = 422


class NotFound(VFError):
    code = "NOT_FOUND"
    http_status = 404


class UnsupportedMedia(VFError):
    code = "UNSUPPORTED_MEDIA"
    http_status = 415


class PayloadTooLarge(VFError):
    code = "PAYLOAD_TOO_LARGE"
    http_status = 413


class SessionExpired(VFError):
    code = "SESSION_EXPIRED"
    http_status = 410

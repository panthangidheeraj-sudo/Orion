"""Tool invocation models (§15)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ToolSchema(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]
    category: str
    online: bool = False
    mutates: bool = False


class ToolCallRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=80)
    arguments: Dict[str, Any] = Field(default_factory=dict)
    conversation_id: Optional[str] = None
    inspection_id: Optional[str] = None
    job_id: Optional[str] = None


class ToolCallResult(BaseModel):
    ok: bool
    tool: str
    duration_ms: float
    source: Optional[str] = None
    error: Optional[str] = None
    reason: Optional[str] = None
    result: Dict[str, Any] = Field(default_factory=dict)


class VoiceTranscribeResponse(BaseModel):
    text: str = ""
    segments: List[Dict[str, Any]] = Field(default_factory=list)
    language: Optional[str] = None
    model: Optional[str] = None
    degraded: bool = False
    reason: Optional[str] = None


class SynthesizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: Optional[str] = Field(default=None, max_length=60)

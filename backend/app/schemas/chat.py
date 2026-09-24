"""Request/response models for the chat surface (§20)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: Optional[str] = None
    image_ids: List[str] = Field(default_factory=list, max_length=8)
    job_id: Optional[str] = None
    inspection_id: Optional[str] = None
    mode: str = Field(default="normal", pattern="^(normal|live)$")
    web: bool = False
    allow_writes: bool = False
    profile: Optional[Dict[str, Any]] = None


class Section(BaseModel):
    kind: str
    title: str
    items: List[str] = Field(default_factory=list)


class Notice(BaseModel):
    level: str
    title: str
    items: List[str] = Field(default_factory=list)
    note: Optional[str] = None


class WorkStep(BaseModel):
    tool: str
    ok: bool
    duration_ms: float
    summary: str


class ModelInfo(BaseModel):
    provider: str
    model_id: str
    accelerator: str
    npu: bool
    synthetic: bool


class ChatResponse(BaseModel):
    conversation_id: str
    message_id: Optional[str] = None
    text: str
    sections: List[Section] = Field(default_factory=list)
    notice: Optional[Notice] = None
    question: Optional[str] = None
    refs: List[Dict[str, Any]] = Field(default_factory=list)
    # Which tools actually produced evidence for this answer.
    evidence_keys: List[str] = Field(default_factory=list)
    work_trail: List[WorkStep] = Field(default_factory=list)
    confidence: Optional[float] = None
    confidence_label: Optional[str] = None
    hazards: List[str] = Field(default_factory=list)
    safety_notes: List[str] = Field(default_factory=list)
    unverified_figures: List[str] = Field(default_factory=list)
    degraded_tools: List[str] = Field(default_factory=list)
    memory: Optional[Dict[str, Any]] = None
    follow_ups: List[str] = Field(default_factory=list)
    model: Optional[ModelInfo] = None
    error: Optional[Dict[str, Any]] = None
    # True when this was ordinary conversation rather than a diagnostic turn.
    conversational: bool = False
    intent: Optional[str] = None
    duration_ms: float = 0.0
    created_at: str


class ConversationCreate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=160)

"""Row shapes for the local store.

These mirror the §14 tables.  The HTTP-facing models live in app/schemas/;
these are the internal representations the memory service hands around.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Conversation(BaseModel):
    id: str
    user_id: Optional[str] = None
    title: Optional[str] = None
    created_at: str
    updated_at: str


class StoredMessage(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str


class Machine(BaseModel):
    id: str
    name: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class Job(BaseModel):
    id: str
    machine_id: Optional[str] = None
    title: Optional[str] = None
    status: str = "open"
    summary: Optional[str] = None
    created_at: str
    updated_at: str


class Inspection(BaseModel):
    id: str
    job_id: str
    mode: str
    started_at: str
    ended_at: Optional[str] = None
    summary: Optional[str] = None


class Finding(BaseModel):
    id: str
    inspection_id: str
    type: Optional[str] = None
    description: str
    confidence: Optional[float] = None
    source: Dict[str, Any] = Field(default_factory=dict)
    created_at: str


class Measurement(BaseModel):
    id: str
    inspection_id: str
    name: str
    value: Optional[float] = None
    unit: Optional[str] = None
    source: Optional[str] = None
    created_at: str


class Memory(BaseModel):
    """A durable memory.  §13 requires confidence and source metadata."""

    id: str
    user_id: Optional[str] = None
    job_id: Optional[str] = None
    memory_type: str
    content: str
    confidence: Optional[float] = None
    source: Dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class JobHistory(BaseModel):
    job: Job
    machine: Optional[Machine] = None
    inspections: List[Inspection] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)
    measurements: List[Measurement] = Field(default_factory=list)
    memories: List[Memory] = Field(default_factory=list)


MEMORY_TYPES = (
    "machine_identity",
    "measurement",
    "fault",
    "repair_action",
    "result",
    "preference",
    "document_association",
)

"""Job, machine and memory models (§13, §14)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MachineCreate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=160)
    manufacturer: Optional[str] = Field(default=None, max_length=120)
    model: Optional[str] = Field(default=None, max_length=120)
    serial_number: Optional[str] = Field(default=None, max_length=120)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class JobCreate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=160)
    machine_id: Optional[str] = None
    machine: Optional[MachineCreate] = None
    status: str = Field(default="open", max_length=40)
    summary: Optional[str] = Field(default=None, max_length=4000)


class JobUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=160)
    status: Optional[str] = Field(default=None, max_length=40)
    summary: Optional[str] = Field(default=None, max_length=4000)
    machine_id: Optional[str] = None


class InspectionCreate(BaseModel):
    job_id: str
    mode: str = Field(default="photo", pattern="^(photo|live|chat)$")


class FindingCreate(BaseModel):
    inspection_id: str
    description: str = Field(min_length=4, max_length=2000)
    type: Optional[str] = Field(default=None, max_length=60)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    source: Dict[str, Any] = Field(default_factory=dict)


class MeasurementCreate(BaseModel):
    inspection_id: str
    name: str = Field(min_length=1, max_length=80)
    value: float
    unit: Optional[str] = Field(default=None, max_length=16)
    source: str = Field(default="technician", max_length=40)


class MemoryCreate(BaseModel):
    memory_type: str
    content: str = Field(min_length=4, max_length=2000)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confirmed: bool = False
    job_id: Optional[str] = None
    source: Dict[str, Any] = Field(default_factory=dict)


class ReportCreate(BaseModel):
    job_id: str
    title: Optional[str] = Field(default=None, max_length=160)
    summary: Optional[str] = Field(default=None, max_length=4000)
    recommendations: List[str] = Field(default_factory=list)

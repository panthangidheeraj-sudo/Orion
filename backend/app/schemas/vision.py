"""Photo and live-mode models (§7, §8, §9)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Detection(BaseModel):
    label: str
    confidence: float
    bbox: List[float]
    bbox_norm: Optional[List[float]] = None
    source: str = "detector"


class TextRegion(BaseModel):
    """§9 OCR record."""
    text: str
    confidence: float
    bbox: List[float]
    source: str


class PhotoAnalyzeRequest(BaseModel):
    question: Optional[str] = Field(default=None, max_length=4000)
    conversation_id: Optional[str] = None
    job_id: Optional[str] = None
    inspection_id: Optional[str] = None
    web: bool = False


class LiveStartRequest(BaseModel):
    conversation_id: Optional[str] = None
    job_id: Optional[str] = None
    inspection_id: Optional[str] = None
    target_label: Optional[str] = Field(default=None, max_length=120)


class LiveFrameResponse(BaseModel):
    session_id: str
    frame_index: int
    detections: List[Dict[str, Any]] = Field(default_factory=list)
    text_regions: List[Dict[str, Any]] = Field(default_factory=list)
    track: Optional[Dict[str, Any]] = None
    scene_change: float = 0.0
    ran: Dict[str, bool] = Field(default_factory=dict)
    vlm: Dict[str, Any] = Field(default_factory=dict)
    analysis: Optional[Dict[str, Any]] = None
    timings_ms: Dict[str, float] = Field(default_factory=dict)

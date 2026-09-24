"""Knowledge vault models (§10, §11)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DocumentSummary(BaseModel):
    id: str
    filename: str
    mime_type: Optional[str] = None
    page_count: Optional[int] = None
    checksum: Optional[str] = None
    chunk_count: int = 0
    indexed: bool = False
    created_at: str


class UploadResult(BaseModel):
    document_id: str
    filename: str
    mime_type: str
    page_count: int
    pages_rendered: int
    checksum: str
    bytes: int
    state: str
    index: Dict[str, Any] = Field(default_factory=dict)
    extraction: Dict[str, Any] = Field(default_factory=dict)
    duplicate_of: Optional[str] = None
    duration_ms: float = 0.0


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=400)
    top_k: int = Field(default=6, ge=1, le=12)
    document_ids: Optional[List[str]] = None

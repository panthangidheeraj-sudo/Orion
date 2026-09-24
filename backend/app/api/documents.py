"""Knowledge vault endpoints (§10, §11, §20)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import FileResponse

from app.api._media import read_upload
from app.knowledge import document_ingest
from app.knowledge.retrieval import search_documents as _search
from app.logging_setup import get_logger
from app.schemas.documents import SearchRequest

log = get_logger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("/upload")
async def upload(file: UploadFile = File(...),
                 title: Optional[str] = Form(None)) -> Dict[str, Any]:
    data = await read_upload(file)
    return await document_ingest.ingest(data, file.filename or "document",
                                        file.content_type, title)


@router.get("")
async def list_documents() -> Dict[str, Any]:
    docs = document_ingest.list_documents()
    return {"documents": docs, "count": len(docs)}


@router.post("/search")
async def search(req: SearchRequest) -> Dict[str, Any]:
    return await _search(req.query, top_k=req.top_k, document_ids=req.document_ids)


@router.get("/{document_id}")
async def get_document(document_id: str) -> Dict[str, Any]:
    return document_ingest.get_document(document_id)


@router.get("/{document_id}/pages/{page}")
async def get_page(document_id: str, page: int) -> FileResponse:
    """Serve a rendered page image — the visual brain, for the UI's page viewer."""
    path = document_ingest.page_image_path(document_id, page)
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=3600"})


@router.delete("/{document_id}")
async def delete_document(document_id: str) -> Dict[str, Any]:
    return document_ingest.delete_document(document_id)

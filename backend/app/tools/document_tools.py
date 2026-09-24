"""Document tools (§11, §12).

``search_documents`` is the text brain; ``get_document_page`` is the visual
brain — it opens a rendered page so the backend can hand that picture to the
VLM as an image input.  The VLM never receives a filesystem path.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agent.tool_registry import registry as tools
from app.knowledge import document_ingest
from app.knowledge.retrieval import search_documents as _search
from app.logging_setup import get_logger
from app.memory import sqlite as db

log = get_logger(__name__)


@tools.tool(
    "search_documents",
    "Search the technician's uploaded manuals, datasheets and schematics. "
    "Returns the most relevant passages with the document and page they came from.",
    {"type": "object", "additionalProperties": False,
     "required": ["query"],
     "properties": {
         "query": {"type": "string", "minLength": 2, "maxLength": 400},
         "top_k": {"type": "integer", "minimum": 1, "maximum": 12, "default": 6},
         "document_ids": {"type": "array",
                          "description": "Restrict the search to these documents."},
     }},
    category="knowledge")
async def search_documents(query: str, top_k: int = 6,
                           document_ids: Optional[List[str]] = None):
    result = await _search(query, top_k=top_k, document_ids=document_ids)
    for r in result["results"]:
        r["content"] = r["content"][:1200]
    return result


@tools.tool(
    "get_document_page",
    "Open a specific page of a document as an image so the diagram, schematic "
    "or table on it can be looked at directly.",
    {"type": "object", "additionalProperties": False,
     "required": ["document_id", "page_number"],
     "properties": {
         "document_id": {"type": "string", "maxLength": 64},
         "page_number": {"type": "integer", "minimum": 1, "maximum": 5000},
     }},
    category="knowledge")
async def get_document_page(document_id: str, page_number: int):
    doc = document_ingest.get_document(document_id)
    path = document_ingest.page_image_path(document_id, page_number)
    row = db.query_one(
        "SELECT width, height, has_text FROM document_pages"
        " WHERE document_id = ? AND page_number = ?", (document_id, page_number))
    text_row = db.query_one(
        "SELECT content FROM document_chunks WHERE document_id = ?"
        " AND page_start <= ? AND page_end >= ? LIMIT 1",
        (document_id, page_number, page_number))
    return {
        "document_id": document_id,
        "filename": doc["filename"],
        "page_number": page_number,
        "page_count": doc["page_count"],
        # Consumed by the backend to build a VLM image input; not a path the
        # model itself ever sees.
        "image_path": str(path),
        "width": (row or {}).get("width"),
        "height": (row or {}).get("height"),
        "has_text_layer": bool((row or {}).get("has_text")),
        "page_text": (text_row or {}).get("content", "")[:1500],
        "source": "local_documents",
    }


@tools.tool(
    "get_document_metadata",
    "Describe an uploaded document: filename, type, page count and whether it "
    "has been indexed for search.",
    {"type": "object", "additionalProperties": False,
     "required": ["document_id"],
     "properties": {"document_id": {"type": "string", "maxLength": 64}}},
    category="knowledge")
async def get_document_metadata(document_id: str):
    doc = document_ingest.get_document(document_id)
    return {**doc, "source": "local_documents"}


@tools.tool(
    "list_documents",
    "List the documents currently in the local knowledge vault.",
    {"type": "object", "additionalProperties": False, "properties": {}},
    category="knowledge")
async def list_documents():
    docs = document_ingest.list_documents()
    return {"documents": docs, "count": len(docs), "source": "local_documents"}

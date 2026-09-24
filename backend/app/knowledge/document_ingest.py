"""Document ingest — the pipeline behind POST /api/documents/upload.

Layout per §11:

    data/documents/<document_id>/
      original.<ext>
      pages/001.png
      extracted/text.json
      extracted/ocr.json
      metadata.json

Safety rules applied here (§24): the filename is sanitised, the path is
contained, the size is capped, the bytes are never executed, and the file is
identified by sniffing its content rather than trusting the client's
Content-Type.  §25: if indexing fails the document still lands on disk and
stays viewable, it just is not searchable, and the record says so.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.errors import NotFound, PayloadTooLarge, UnsupportedMedia
from app.knowledge import page_render, text_extract
from app.knowledge.chunking import chunk_pages
from app.logging_setup import get_logger
from app.memory import sqlite as db
from app.memory import vector_store as vs
from app.models.base import ImageRef
from app.models.registry import registry
from app.util import contained_path, new_id, preview, safe_filename, sha256_bytes, timed, utc_now

log = get_logger(__name__)

MAGIC = [
    (b"%PDF-", "application/pdf", ".pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"RIFF", "image/webp", ".webp"),
    (b"II*\x00", "image/tiff", ".tif"),
    (b"MM\x00*", "image/tiff", ".tif"),
    (b"PK\x03\x04", "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document", ".docx"),
]


# Formats that always carry a signature. If the name or the declared type
# claims one of these and the bytes do not match, the upload is a lie and is
# refused — a renamed executable must never be accepted as a PDF (§24).
BINARY_KINDS = {"pdf", "image", "docx"}


def sniff(data: bytes, filename: str, declared: Optional[str]) -> tuple[str, str]:
    """Identify the upload from its bytes, not from what the client claimed."""
    head = data[:16]
    for magic, mime, ext in MAGIC:
        if head.startswith(magic):
            if mime.endswith("wordprocessingml.document") and not filename.lower().endswith(".docx"):
                break  # a zip that is not a .docx
            return mime, ext

    ext = Path(filename).suffix.lower()
    declared_mime = (declared or "").split(";")[0].strip().lower()
    claimed = text_extract.SUPPORTED_EXT.get(ext) or text_extract.SUPPORTED_MIME.get(declared_mime)

    if claimed in BINARY_KINDS:
        raise UnsupportedMedia(
            f"this file is named or declared as {claimed} but its contents are not",
            filename=safe_filename(filename), declared=declared)

    if claimed == "text" or (not claimed and _looks_like_text(data)):
        mime = declared_mime if declared_mime in text_extract.SUPPORTED_MIME else "text/plain"
        return mime, (ext or ".txt")

    raise UnsupportedMedia(
        "the uploaded bytes are not a supported document type",
        filename=safe_filename(filename), declared=declared,
        supported=sorted(set(text_extract.SUPPORTED_EXT)),
    )


def _looks_like_text(data: bytes) -> bool:
    """Decide by content whether an unlabelled upload is readable text."""
    sample = data[:4096]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    printable = sum(1 for b in sample if 9 <= b <= 13 or 32 <= b < 127 or b >= 160)
    return printable / max(1, len(sample)) > 0.92


def document_root(document_id: str) -> Path:
    return contained_path(settings.documents_dir, document_id)


async def ingest(data: bytes, filename: str, declared_mime: Optional[str] = None,
                 title: Optional[str] = None) -> Dict[str, Any]:
    if len(data) > settings.max_upload_bytes:
        raise PayloadTooLarge(
            f"upload is {len(data) // 1048576} MB; the limit is "
            f"{settings.max_upload_bytes // 1048576} MB",
            bytes=len(data), limit=settings.max_upload_bytes)
    if not data:
        raise UnsupportedMedia("the upload is empty")

    mime, ext = sniff(data, filename, declared_mime)
    clean_name = safe_filename(title or filename, fallback=f"document{ext}")
    doc_id = new_id("doc")
    root = document_root(doc_id)
    (root / "pages").mkdir(parents=True, exist_ok=True)
    (root / "extracted").mkdir(parents=True, exist_ok=True)

    original = root / f"original{ext}"
    original.write_bytes(data)
    checksum = sha256_bytes(data)

    duplicate = db.query_one("SELECT id, filename FROM documents WHERE checksum = ?", (checksum,))

    with timed() as t:
        extraction = text_extract.extract(original, mime)

        if extraction.kind == "pdf":
            pages = page_render.render_pdf_pages(original, root / "pages")
        elif extraction.kind == "image":
            pages = page_render.copy_image_page(original, root / "pages")
        else:
            pages = []

        ocr_records = await _ocr_pages(extraction, pages)

        (root / "extracted" / "text.json").write_text(
            json.dumps({"engine": extraction.engine,
                        "pages": [{"number": p.number, "text": p.text} for p in extraction.pages]},
                       ensure_ascii=False), encoding="utf-8")
        (root / "extracted" / "ocr.json").write_text(
            json.dumps(ocr_records, ensure_ascii=False), encoding="utf-8")

        page_count = max(extraction.page_count, len(pages), 1)
        db.insert("documents", {
            "id": doc_id, "filename": clean_name, "mime_type": mime,
            "path": str(original), "checksum": checksum,
            "page_count": page_count, "created_at": utc_now(),
        })
        for p in pages:
            db.execute(
                "INSERT OR REPLACE INTO document_pages (document_id, page_number, image_path,"
                " width, height, has_text) VALUES (?,?,?,?,?,?)",
                (doc_id, p["page_number"], p["image_path"], p["width"], p["height"],
                 1 if _page_has_text(extraction, p["page_number"]) else 0))

        index = await _index(doc_id, extraction, ocr_records)

    (root / "metadata.json").write_text(json.dumps({
        "document_id": doc_id, "filename": clean_name, "mime_type": mime,
        "checksum": checksum, "created_at": utc_now(),
        "extraction": extraction.to_dict(),
        "pages_rendered": len(pages), "index": index,
        "duplicate_of": duplicate["id"] if duplicate else None,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    log.info("ingested %s (%s, %d page(s), %d chunk(s)) in %.0f ms",
             preview(clean_name, 60), mime, page_count, index.get("chunks", 0), t["ms"])

    return {
        "document_id": doc_id,
        "filename": clean_name,
        "mime_type": mime,
        "page_count": page_count,
        "pages_rendered": len(pages),
        "checksum": checksum,
        "bytes": len(data),
        "extraction": extraction.to_dict(),
        "index": index,
        "duplicate_of": duplicate["id"] if duplicate else None,
        "duration_ms": t["ms"],
        "state": "ready" if index.get("chunks") else "stored_not_indexed",
    }


def _page_has_text(extraction, number: int) -> bool:
    for p in extraction.pages:
        if p.number == number:
            return p.char_count > 24
    return False


async def _ocr_pages(extraction, rendered: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fill in pages with no text layer, when an OCR provider is actually ready."""
    ocr = registry.ocr()
    if not ocr.is_ready() or not rendered:
        return []
    targets = [p for p in rendered if not _page_has_text(extraction, p["page_number"])][:60]
    records: List[Dict[str, Any]] = []
    for page in targets:
        ref = ImageRef(id=f"page_{page['page_number']}", path=page["image_path"],
                       width=page["width"], height=page["height"],
                       mime_type="image/png", source="document_page")
        try:
            regions = await ocr.extract(ref)
        except Exception as exc:
            log.warning("ocr failed on page %d: %s", page["page_number"], type(exc).__name__)
            continue
        text = " ".join(r["text"] for r in regions)
        records.append({"page_number": page["page_number"], "text": text, "regions": regions})
        for p in extraction.pages:
            if p.number == page["page_number"] and not p.text:
                p.text, p.char_count, p.needs_ocr = text, len(text), False
    extraction.total_chars = sum(p.char_count for p in extraction.pages)
    return records


async def _index(document_id: str, extraction, ocr_records) -> Dict[str, Any]:
    chunks = chunk_pages(extraction.pages)
    if not chunks:
        return {"chunks": 0, "vectors": 0,
                "reason": "no extractable text — the document is still viewable page by page"}

    now = utc_now()
    rows = []
    fts_rows = []
    for c in chunks:
        cid = new_id("chk")
        rows.append((cid, document_id, c.page_start, c.page_end, c.content,
                     json.dumps({"heading": c.heading, "index": c.index,
                                 "page_spans": c.page_spans or []}), now))
        fts_rows.append((c.content, cid, document_id))
    db.execute_many(
        "INSERT INTO document_chunks (id, document_id, page_start, page_end, content,"
        " metadata_json, created_at) VALUES (?,?,?,?,?,?,?)", rows)
    db.execute_many(
        "INSERT INTO chunk_fts (content, chunk_id, document_id) VALUES (?,?,?)", fts_rows)

    embedder = registry.embedding()
    vectors = 0
    if embedder.is_ready():
        try:
            embeddings = await embedder.embed([r[4] for r in rows])
            vectors = vs.add_many(vs.DOCUMENT_CHUNK,
                                  [(r[0], e) for r, e in zip(rows, embeddings)],
                                  embedder.model_id)
        except Exception as exc:
            # §25: indexing failure leaves the document searchable lexically.
            log.warning("embedding failed for %s: %s", document_id, type(exc).__name__)

    return {
        "chunks": len(rows), "vectors": vectors,
        "embedding_model": embedder.model_id if embedder.is_ready() else None,
        "embedding_synthetic": embedder.health().synthetic if embedder.is_ready() else None,
        "lexical_index": "fts5",
        "ocr_pages": len(ocr_records),
    }


# ------------------------------------------------------------------ queries

def list_documents() -> List[Dict[str, Any]]:
    rows = db.query(
        "SELECT d.*, (SELECT COUNT(*) FROM document_chunks c WHERE c.document_id = d.id)"
        " AS chunk_count FROM documents d ORDER BY d.created_at DESC")
    for r in rows:
        r.pop("path", None)  # internal paths never leave the process
        r["indexed"] = bool(r.get("chunk_count"))
    return rows


def get_document(document_id: str) -> Dict[str, Any]:
    row = db.query_one("SELECT * FROM documents WHERE id = ?", (document_id,))
    if not row:
        raise NotFound("no such document", document_id=document_id)
    pages = db.query(
        "SELECT page_number, width, height, has_text FROM document_pages"
        " WHERE document_id = ? ORDER BY page_number", (document_id,))
    chunks = db.query_one(
        "SELECT COUNT(*) AS n FROM document_chunks WHERE document_id = ?", (document_id,))
    row.pop("path", None)
    return {**row, "pages": pages, "chunk_count": (chunks or {}).get("n", 0),
            "indexed": bool((chunks or {}).get("n"))}


def page_image_path(document_id: str, page_number: int) -> Path:
    row = db.query_one(
        "SELECT image_path FROM document_pages WHERE document_id = ? AND page_number = ?",
        (document_id, page_number))
    if not row or not row["image_path"]:
        raise NotFound("no rendered image for that page",
                       document_id=document_id, page_number=page_number)
    path = Path(row["image_path"])
    # Re-verify containment: the row could predate a config change.
    root = settings.documents_dir.resolve()
    if root not in path.resolve().parents:
        raise NotFound("page image is outside the document store", document_id=document_id)
    if not path.exists():
        raise NotFound("page image is missing from disk", document_id=document_id,
                       page_number=page_number)
    return path


def delete_document(document_id: str) -> Dict[str, Any]:
    row = db.query_one("SELECT id FROM documents WHERE id = ?", (document_id,))
    if not row:
        raise NotFound("no such document", document_id=document_id)
    chunk_ids = [r["id"] for r in db.query(
        "SELECT id FROM document_chunks WHERE document_id = ?", (document_id,))]
    vs.delete_for(vs.DOCUMENT_CHUNK, chunk_ids)
    db.execute("DELETE FROM chunk_fts WHERE document_id = ?", (document_id,))
    db.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
    db.execute("DELETE FROM document_pages WHERE document_id = ?", (document_id,))
    db.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    import shutil

    shutil.rmtree(document_root(document_id), ignore_errors=True)
    return {"document_id": document_id, "deleted": True, "chunks_removed": len(chunk_ids)}

"""Chunking (§12).

Chunks respect page boundaries so every chunk keeps a page reference, break on
paragraphs and sentences rather than mid-word, and overlap slightly so a
procedure split across a boundary is still retrievable from either side.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from app.config import settings

_PARA = re.compile(r"\n\s*\n")
_SENT = re.compile(r"(?<=[.!?:;])\s+")
_HEADING = re.compile(r"^\s*((?:\d+\.){1,4}\s*\S.*|[A-Z][A-Z0-9 /&'\-]{6,}|#{1,6}\s+\S.*)$", re.M)


@dataclass
class Chunk:
    content: str
    page_start: int
    page_end: int
    heading: str = ""
    index: int = 0
    # Where each page's text sits inside ``content``: (page, start, end).
    # Retrieval uses this to cite the page the matching sentence is actually
    # printed on, instead of the first page the chunk happens to begin on.
    page_spans: List[List[int]] = None  # type: ignore[assignment]

    def to_dict(self) -> Dict[str, Any]:
        return {"content": self.content, "page_start": self.page_start,
                "page_end": self.page_end, "heading": self.heading,
                "index": self.index, "page_spans": self.page_spans or []}

    def page_at(self, offset: int) -> int:
        for page, start, end in (self.page_spans or []):
            if start <= offset < end:
                return page
        return self.page_start


def _split_long(text: str, target: int) -> List[str]:
    if len(text) <= target:
        return [text]
    out: List[str] = []
    buf = ""
    for sentence in _SENT.split(text):
        if buf and len(buf) + len(sentence) + 1 > target:
            out.append(buf.strip())
            buf = sentence
        else:
            buf = f"{buf} {sentence}".strip()
    if buf.strip():
        out.append(buf.strip())
    # A single sentence longer than the target still has to be cut somewhere.
    final: List[str] = []
    for piece in out:
        while len(piece) > target * 1.6:
            final.append(piece[:target].strip())
            piece = piece[target:]
        if piece.strip():
            final.append(piece.strip())
    return final


def chunk_pages(pages: Sequence[Any], target: int = 0, overlap: int = 0) -> List[Chunk]:
    """``pages`` is a sequence of objects with ``.number`` and ``.text``.

    Pieces are collected with the page they came from, then packed into chunks,
    so ``page_start``/``page_end`` describe the text a chunk actually contains
    rather than wherever the packer happened to be standing.
    """
    target = target or settings.chunk_target_chars
    overlap = overlap if overlap else settings.chunk_overlap_chars

    pieces: List[tuple] = []  # (page_number, heading, text)
    heading = ""
    for page in pages:
        text = (getattr(page, "text", "") or "").strip()
        if not text:
            continue
        found = _HEADING.findall(text)
        if found:
            heading = " ".join(found[0].split())[:120]
        for para in _PARA.split(text):
            para = " ".join(para.split())
            if not para:
                continue
            for piece in _split_long(para, target):
                if piece:
                    pieces.append((page.number, heading, piece))

    chunks: List[Chunk] = []
    buf = ""
    buf_pages: List[int] = []
    buf_heading = ""
    buf_spans: List[List[int]] = []

    def note_span(page_no: int, start: int, end: int) -> None:
        if buf_spans and buf_spans[-1][0] == page_no:
            buf_spans[-1][2] = end
        else:
            buf_spans.append([page_no, start, end])

    def flush() -> None:
        nonlocal buf, buf_pages, buf_heading, buf_spans
        if not buf.strip():
            return
        chunks.append(Chunk(buf.strip(), min(buf_pages), max(buf_pages),
                            buf_heading, len(chunks), list(buf_spans)))
        buf, buf_pages, buf_spans = "", [], []

    # A citation is only useful if it points at the right page, so a chunk is
    # closed at a page boundary once it already carries enough substance to
    # stand alone. Without this a short manual becomes one chunk that cites
    # page 1 for text printed on page 4.
    page_break_floor = int(target * 0.45)

    for page_no, head, piece in pieces:
        crosses_page = bool(buf_pages) and page_no != buf_pages[-1]
        if buf and crosses_page and len(buf) >= page_break_floor:
            flush()
            buf, buf_pages, buf_heading = piece, [page_no], head
            note_span(page_no, 0, len(piece))
            continue
        if buf and len(buf) + len(piece) + 1 > target:
            tail = buf[-overlap:] if overlap else ""
            if tail and " " in tail:
                tail = tail[tail.index(" ") + 1:]
            last_page = buf_pages[-1] if buf_pages else page_no
            flush()
            buf = f"{tail} {piece}".strip() if tail else piece
            buf_pages = [last_page, page_no] if tail else [page_no]
            buf_heading = head
            if tail:
                note_span(last_page, 0, len(tail))
            note_span(page_no, len(buf) - len(piece), len(buf))
        else:
            if not buf:
                buf_heading = head
            start = len(buf) + (1 if buf else 0)
            buf = f"{buf} {piece}".strip()
            buf_pages.append(page_no)
            note_span(page_no, start, len(buf))
    flush()
    return chunks

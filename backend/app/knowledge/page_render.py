"""Page rendering — the "visual brain" half of §11.

Every page becomes a PNG under ``data/documents/<id>/pages/NNN.png`` so the
agent can hand the VLM a picture of page 47 rather than a paraphrase of it.
The VLM never gets a filesystem path from a tool argument; it gets an image
the backend opened from a validated, contained location.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.logging_setup import get_logger

log = get_logger(__name__)


def render_pdf_pages(pdf_path: Path, out_dir: Path, dpi: Optional[int] = None,
                     max_pages: int = 400) -> List[Dict[str, Any]]:
    dpi = dpi or settings.page_render_dpi
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        import pymupdf  # type: ignore
    except Exception as exc:
        log.warning("page rendering unavailable: %s", type(exc).__name__)
        return []

    rendered: List[Dict[str, Any]] = []
    doc = pymupdf.open(str(pdf_path))
    try:
        zoom = dpi / 72.0
        matrix = pymupdf.Matrix(zoom, zoom)
        for i, page in enumerate(doc, start=1):
            if i > max_pages:
                log.info("stopped rendering at %d pages", max_pages)
                break
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            dest = out_dir / f"{i:03d}.png"
            pix.save(str(dest))
            rendered.append({"page_number": i, "image_path": str(dest),
                             "width": pix.width, "height": pix.height})
    finally:
        doc.close()
    return rendered


def copy_image_page(src: Path, out_dir: Path) -> List[Dict[str, Any]]:
    """An uploaded picture is a one-page visual document."""
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "001.png"
    with Image.open(src) as img:
        img = img.convert("RGB")
        img.save(dest, format="PNG")
        return [{"page_number": 1, "image_path": str(dest),
                 "width": img.width, "height": img.height}]

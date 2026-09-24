"""Shared upload handling for the API layer.

Images are decoded and re-encoded before they touch disk, so what is stored is
a picture and cannot be anything else (§24: uploaded files are never executed).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import UploadFile

from app.config import settings
from app.errors import PayloadTooLarge, UnsupportedMedia
from app.memory import sqlite as db
from app.models._imaging import save_bytes_as_image
from app.util import contained_path, new_id, sha256_bytes, utc_now

MAX_IMAGE_BYTES = 40 * 1024 * 1024


async def read_upload(file: UploadFile, limit: int = 0) -> bytes:
    limit = limit or settings.max_upload_bytes
    data = await file.read()
    if len(data) > limit:
        raise PayloadTooLarge(
            f"file is {len(data) // 1048576} MB; the limit is {limit // 1048576} MB",
            bytes=len(data), limit=limit)
    if not data:
        raise UnsupportedMedia("the uploaded file is empty")
    return data


def store_image(data: bytes, source: str = "photo",
                conversation_id: Optional[str] = None,
                inspection_id: Optional[str] = None) -> Dict[str, Any]:
    if len(data) > MAX_IMAGE_BYTES:
        raise PayloadTooLarge(
            f"image is {len(data) // 1048576} MB; the limit is {MAX_IMAGE_BYTES // 1048576} MB",
            bytes=len(data))
    image_id = new_id("img")
    dest = contained_path(settings.images_dir, f"{image_id}.jpg")
    try:
        width, height, mime = save_bytes_as_image(data, dest)
    except Exception as exc:
        raise UnsupportedMedia(f"that file is not a readable image ({type(exc).__name__})")

    row = {
        "id": image_id, "conversation_id": conversation_id, "inspection_id": inspection_id,
        "path": str(dest), "mime_type": mime, "width": width, "height": height,
        "source": source, "checksum": sha256_bytes(data), "created_at": utc_now(),
    }
    db.insert("images", row)
    return {"image_id": image_id, "width": width, "height": height,
            "mime_type": mime, "bytes": dest.stat().st_size, "source": source}

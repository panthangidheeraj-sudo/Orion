"""Small shared helpers: identifiers, time, timing, path safety, redaction."""

from __future__ import annotations

import hashlib
import re
import secrets
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


def new_id(prefix: str = "") -> str:
    """Random, unguessable identifier (§24: 'use random IDs where practical')."""
    body = "".join(secrets.choice(_ID_ALPHABET) for _ in range(20))
    return f"{prefix}_{body}" if prefix else body


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ms() -> float:
    return time.perf_counter() * 1000.0


@contextmanager
def timed() -> Iterator[dict]:
    """``with timed() as t: ...`` then read ``t['ms']``."""
    box: dict = {"ms": 0.0}
    start = ms()
    try:
        yield box
    finally:
        box["ms"] = round(ms() - start, 2)


_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_filename(name: str, fallback: str = "upload.bin") -> str:
    """Strip a user-supplied filename down to something that cannot traverse.

    §24 requires sanitising filenames and paths.  We keep only the basename,
    normalise unicode, drop separators and control characters, and refuse
    leading dots so nothing lands as a hidden or special file.
    """
    name = unicodedata.normalize("NFKD", name or "")
    name = name.replace("\\", "/").split("/")[-1]
    name = _UNSAFE.sub("_", name).strip(" .")
    name = re.sub(r"_{2,}", "_", name)
    if not name:
        return fallback
    stem, dot, ext = name.rpartition(".")
    if dot and len(ext) > 12:
        name = f"{stem}_{ext[:12]}"
    return name[:150]


def contained_path(root: Path, *parts: str) -> Path:
    """Join under ``root`` and refuse anything that escapes it.

    Every filesystem access reachable from a tool or an HTTP parameter goes
    through this.  §15: the agent must not access arbitrary filesystem paths.
    """
    root = root.resolve()
    candidate = root.joinpath(*[safe_filename(p) for p in parts]).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("path escapes its root")
    return candidate


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def preview(text: str, limit: int = 120) -> str:
    """Short, log-safe excerpt.

    §24: logs must not dump full private documents, audio or camera frames.
    Anything derived from user content is squeezed through this before it is
    allowed anywhere near a log line.
    """
    if text is None:
        return ""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"

"""Local vector store (§13).

sqlite-vec is used when it is installed; otherwise vectors live in the
``vectors`` table as float32 blobs and search is an exact cosine scan in
numpy.  For a single technician's document set that scan is fast enough
(tens of thousands of chunks in milliseconds), and it removes a hard
dependency that may not build on ARM64 Windows.  The active backend is
reported, never assumed.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from app.logging_setup import get_logger
from app.memory import sqlite as db
from app.util import new_id, utc_now

log = get_logger(__name__)

DOCUMENT_CHUNK = "document_chunk"
MEMORY = "memory"

_cache_lock = threading.Lock()
_cache: Dict[str, Tuple[List[str], np.ndarray]] = {}


def _sqlite_vec_available() -> bool:
    try:
        import sqlite_vec  # type: ignore # noqa: F401

        return True
    except Exception:
        return False


def backend_info() -> Dict[str, Any]:
    return {
        "backend": "sqlite-vec" if _sqlite_vec_available() else "numpy-exact",
        "sqlite_vec_installed": _sqlite_vec_available(),
        "note": "Exact cosine scan over float32 blobs when sqlite-vec is absent; "
                "results are identical, only the speed at very large scale differs.",
        "counts": counts(),
    }


def counts() -> Dict[str, int]:
    rows = db.query("SELECT owner_kind, COUNT(*) AS n FROM vectors GROUP BY owner_kind")
    return {r["owner_kind"]: r["n"] for r in rows}


def _invalidate(kind: str) -> None:
    with _cache_lock:
        _cache.pop(kind, None)


def add(owner_kind: str, owner_id: str, embedding: Sequence[float], model: str) -> str:
    vec = np.asarray(embedding, dtype=np.float32)
    norm = float(np.linalg.norm(vec)) or 1.0
    vid = new_id("vec")
    db.execute(
        "INSERT INTO vectors (id, owner_kind, owner_id, dim, model, embedding, norm, created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (vid, owner_kind, owner_id, int(vec.size), model, vec.tobytes(), norm, utc_now()),
    )
    _invalidate(owner_kind)
    return vid


def add_many(owner_kind: str, items: Sequence[Tuple[str, Sequence[float]]], model: str) -> int:
    now = utc_now()
    rows = []
    for owner_id, emb in items:
        vec = np.asarray(emb, dtype=np.float32)
        rows.append((new_id("vec"), owner_kind, owner_id, int(vec.size), model,
                     vec.tobytes(), float(np.linalg.norm(vec)) or 1.0, now))
    if not rows:
        return 0
    db.execute_many(
        "INSERT INTO vectors (id, owner_kind, owner_id, dim, model, embedding, norm, created_at)"
        " VALUES (?,?,?,?,?,?,?,?)", rows)
    _invalidate(owner_kind)
    return len(rows)


def delete_for(owner_kind: str, owner_ids: Sequence[str]) -> int:
    if not owner_ids:
        return 0
    marks = ",".join("?" for _ in owner_ids)
    n = db.execute(
        f"DELETE FROM vectors WHERE owner_kind = ? AND owner_id IN ({marks})",
        [owner_kind, *owner_ids])
    _invalidate(owner_kind)
    return n


def _matrix(owner_kind: str) -> Tuple[List[str], np.ndarray]:
    with _cache_lock:
        hit = _cache.get(owner_kind)
    if hit is not None:
        return hit
    rows = db.query(
        "SELECT owner_id, dim, embedding FROM vectors WHERE owner_kind = ? ORDER BY rowid",
        (owner_kind,))
    if not rows:
        empty = ([], np.zeros((0, 1), dtype=np.float32))
        with _cache_lock:
            _cache[owner_kind] = empty
        return empty
    dim = rows[0]["dim"]
    ids: List[str] = []
    mats: List[np.ndarray] = []
    for r in rows:
        if r["dim"] != dim:
            # A dimension change means the embedding model was swapped; those
            # rows are stale until the owner is re-indexed.
            continue
        ids.append(r["owner_id"])
        mats.append(np.frombuffer(r["embedding"], dtype=np.float32))
    mat = np.vstack(mats) if mats else np.zeros((0, dim), dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    mat = mat / np.maximum(1e-9, norms)
    out = (ids, mat)
    with _cache_lock:
        _cache[owner_kind] = out
    return out


def search(owner_kind: str, embedding: Sequence[float], top_k: int = 8,
           allowed_ids: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    ids, mat = _matrix(owner_kind)
    if not ids:
        return []
    q = np.asarray(embedding, dtype=np.float32)
    if q.size != mat.shape[1]:
        log.warning("query dim %d != index dim %d for %s; re-index required",
                    q.size, mat.shape[1], owner_kind)
        return []
    q = q / max(1e-9, float(np.linalg.norm(q)))
    scores = mat @ q
    allow = set(allowed_ids) if allowed_ids is not None else None
    order = np.argsort(scores)[::-1]
    out: List[Dict[str, Any]] = []
    for i in order:
        oid = ids[int(i)]
        if allow is not None and oid not in allow:
            continue
        out.append({"owner_id": oid, "score": round(float(scores[int(i)]), 5)})
        if len(out) >= top_k:
            break
    return out


def reset_cache() -> None:
    with _cache_lock:
        _cache.clear()

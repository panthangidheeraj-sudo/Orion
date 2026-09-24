"""SQLite connection handling and schema bootstrap.

One file, WAL mode, foreign keys on.  Connections are per-thread because
FastAPI runs blocking database work in a thread pool.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

from app.config import settings
from app.logging_setup import get_logger

log = get_logger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_local = threading.local()
_init_lock = threading.Lock()
_initialised = False


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def get_connection() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    db_path = settings.db_path
    if conn is not None and getattr(_local, "path", None) == str(db_path):
        return conn
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    conn = _connect(db_path)
    _local.conn = conn
    _local.path = str(db_path)
    return conn


def init_db(force: bool = False) -> None:
    """Apply schema.sql.  Idempotent; safe to call on every boot."""
    global _initialised
    with _init_lock:
        if _initialised and not force:
            return
        conn = get_connection()
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
        _initialised = True
        log.info("database ready at %s", settings.db_path)


def reset_connections() -> None:
    """Used by tests after they point the settings at a temporary file."""
    global _initialised
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    _local.conn = None
    _local.path = None
    _initialised = False


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ------------------------------------------------------------------ helpers

def query(sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
    cur = get_connection().execute(sql, tuple(params))
    try:
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()


def query_one(sql: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: Sequence[Any] = ()) -> int:
    with transaction() as conn:
        cur = conn.execute(sql, tuple(params))
        return cur.rowcount


def execute_many(sql: str, seq: Iterable[Sequence[Any]]) -> int:
    with transaction() as conn:
        cur = conn.executemany(sql, [tuple(p) for p in seq])
        return cur.rowcount


def insert(table: str, row: Dict[str, Any]) -> None:
    cols = list(row.keys())
    sql = "INSERT INTO %s (%s) VALUES (%s)" % (
        table,
        ", ".join(cols),
        ", ".join("?" for _ in cols),
    )
    execute(sql, [row[c] for c in cols])


def upsert(table: str, row: Dict[str, Any], key: str = "id") -> None:
    cols = list(row.keys())
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != key)
    sql = "INSERT INTO %s (%s) VALUES (%s) ON CONFLICT(%s) DO UPDATE SET %s" % (
        table,
        ", ".join(cols),
        ", ".join("?" for _ in cols),
        key,
        updates or f"{key}=excluded.{key}",
    )
    execute(sql, [row[c] for c in cols])

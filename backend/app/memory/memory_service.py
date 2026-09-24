"""Memory service (§13).

Three kinds of memory:

*Session* — the live conversation, visual state and recent tool results.  Held
by the orchestrator and the live session, not here.

*User* — durable preferences and facts, "useful ones only".

*Job* — the important one.  Machine, symptoms, detections, measurements,
manual evidence, likely cause, action, result; retrieved again when the
technician reopens that machine.

The write policy is enforced in code rather than left to prose.  Speculation,
chatter and unconfirmed guesses are refused with a reason, and every stored
memory carries confidence and source metadata.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

from app.errors import NotFound, ValidationFailed
from app.logging_setup import get_logger
from app.memory import sqlite as db
from app.memory import vector_store as vs
from app.memory.schemas import MEMORY_TYPES
from app.models.registry import registry
from app.util import new_id, preview, utc_now

log = get_logger(__name__)

# Phrases that mark a statement as not yet established.  §13: do not store
# temporary guesses, hallucinated diagnoses or unconfirmed speculation.
SPECULATIVE = re.compile(
    r"\b(maybe|might be|could be|perhaps|possibly|i think|probably|not sure|unsure|"
    r"seems like|appears to be|guess|assume|assuming|unconfirmed|tbd|unknown)\b", re.I)
CHATTER = re.compile(
    r"^\s*(hi|hey|hello|thanks|thank you|ok|okay|cool|nice|yes|no|sure|got it|"
    r"good morning|good evening|bye)\b[\s!.?]*$", re.I)
MIN_CONTENT = 12


def _normalise(content: str) -> str:
    """For duplicate detection: case, spacing and trailing punctuation don't count."""
    return " ".join((content or "").lower().split()).rstrip(" .;,")


class WritePolicy:
    """Decides whether a candidate memory is allowed to become durable."""

    @staticmethod
    def evaluate(memory_type: str, content: str, confidence: Optional[float],
                 source: Optional[Dict[str, Any]], confirmed: bool,
                 job_id: Optional[str] = None) -> Dict[str, Any]:
        content = (content or "").strip()
        if memory_type not in MEMORY_TYPES:
            return {"store": False, "reason": f"unknown memory_type '{memory_type}'",
                    "allowed": list(MEMORY_TYPES)}
        if len(content) < MIN_CONTENT:
            return {"store": False, "reason": "too short to be a useful durable memory"}
        if CHATTER.match(content):
            return {"store": False, "reason": "conversational filler is not stored (§13)"}
        if SPECULATIVE.search(content) and not confirmed:
            return {"store": False,
                    "reason": "statement is speculative and not marked confirmed; "
                              "confirm it or record it as a finding instead"}
        if not source:
            return {"store": False,
                    "reason": "durable memories require source metadata (§13)"}
        if confidence is None:
            return {"store": False, "reason": "durable memories require a confidence value (§13)"}
        if not confirmed and confidence < 0.6:
            return {"store": False,
                    "reason": f"confidence {confidence:.2f} is below the 0.60 bar for an "
                              "unconfirmed memory"}

        # §13: "Do not store everything automatically." The same fact recorded
        # twice is noise that dilutes every later retrieval, so an existing
        # identical memory of the same type wins and the write is refused.
        target = _normalise(content)
        existing = db.query(
            "SELECT id, content FROM memories WHERE memory_type = ?"
            " AND (job_id IS ? OR job_id = ?)",
            (memory_type, job_id, job_id))
        for row in existing:
            if _normalise(row["content"]) == target:
                return {"store": False, "duplicate_of": row["id"],
                        "reason": "an identical memory is already stored for this "
                                  "type and job"}

        return {"store": True, "reason": "meets the §13 write policy"}


# -------------------------------------------------------------------- user

LOCAL_USER_ID = "user_local"


def ensure_user(display_name: Optional[str] = None) -> Dict[str, Any]:
    """The single local technician (§14 ``users``).

    V1 is one person on one machine, so there is no sign-in — but the row has
    to exist for user-scoped memory (§13's "user memory") to hang off
    something, and for a later multi-user build to have somewhere to go.
    """
    row = db.query_one("SELECT * FROM users WHERE id = ?", (LOCAL_USER_ID,))
    now = utc_now()
    if row is None:
        row = {"id": LOCAL_USER_ID, "display_name": display_name or "Technician",
               "created_at": now, "updated_at": now}
        db.insert("users", row)
        log.info("created the local user record")
        return row
    if display_name and display_name != row["display_name"]:
        db.execute("UPDATE users SET display_name = ?, updated_at = ? WHERE id = ?",
                   (display_name, now, LOCAL_USER_ID))
        row = db.query_one("SELECT * FROM users WHERE id = ?", (LOCAL_USER_ID,))
    return row


def user_profile() -> Dict[str, Any]:
    """The local user plus the preferences durable memory has accepted."""
    user = ensure_user()
    prefs = db.query(
        "SELECT * FROM memories WHERE memory_type = 'preference' ORDER BY updated_at DESC")
    return {**user, "preferences": prefs, "preference_count": len(prefs)}


# ----------------------------------------------------------- conversations

def create_conversation(title: Optional[str] = None, user_id: Optional[str] = None) -> Dict[str, Any]:
    now = utc_now()
    row = {"id": new_id("conv"), "user_id": user_id or ensure_user()["id"],
           "title": (title or "New inspection").strip()[:160],
           "created_at": now, "updated_at": now}
    db.insert("conversations", row)
    return row


def list_conversations(limit: int = 50) -> List[Dict[str, Any]]:
    return db.query(
        "SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id)"
        " AS message_count FROM conversations c ORDER BY c.updated_at DESC LIMIT ?", (limit,))


def get_conversation(conversation_id: str) -> Dict[str, Any]:
    row = db.query_one("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
    if not row:
        raise NotFound("no such conversation", conversation_id=conversation_id)
    return row


def ensure_conversation(conversation_id: Optional[str], title: Optional[str] = None) -> Dict[str, Any]:
    if conversation_id:
        return get_conversation(conversation_id)
    return create_conversation(title)


def rename_conversation(conversation_id: str, title: str) -> Dict[str, Any]:
    get_conversation(conversation_id)
    db.execute("UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
               (title.strip()[:160], utc_now(), conversation_id))
    return get_conversation(conversation_id)


def delete_conversation(conversation_id: str) -> Dict[str, Any]:
    get_conversation(conversation_id)
    db.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
    db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    return {"conversation_id": conversation_id, "deleted": True}


def add_message(conversation_id: str, role: str, content: str,
                metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    row = {"id": new_id("msg"), "conversation_id": conversation_id, "role": role,
           "content": content, "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
           "created_at": utc_now()}
    db.insert("messages", row)
    db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
               (row["created_at"], conversation_id))
    return row


def get_messages(conversation_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    rows = db.query(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at DESC, rowid DESC"
        " LIMIT ?", (conversation_id, limit))
    rows.reverse()
    for r in rows:
        try:
            r["metadata"] = json.loads(r.pop("metadata_json") or "{}")
        except Exception:
            r["metadata"] = {}
    return rows


# ---------------------------------------------------------------- machines

def upsert_machine(name: Optional[str] = None, manufacturer: Optional[str] = None,
                   model: Optional[str] = None, serial_number: Optional[str] = None,
                   metadata: Optional[Dict[str, Any]] = None,
                   machine_id: Optional[str] = None) -> Dict[str, Any]:
    now = utc_now()
    existing = None
    if machine_id:
        existing = db.query_one("SELECT * FROM machines WHERE id = ?", (machine_id,))
    if existing is None and serial_number:
        existing = db.query_one("SELECT * FROM machines WHERE serial_number = ?", (serial_number,))
    if existing is None and name:
        existing = db.query_one("SELECT * FROM machines WHERE name = ?", (name,))

    if existing:
        merged = {
            "name": name or existing["name"],
            "manufacturer": manufacturer or existing["manufacturer"],
            "model": model or existing["model"],
            "serial_number": serial_number or existing["serial_number"],
            "metadata_json": json.dumps({**json.loads(existing["metadata_json"] or "{}"),
                                         **(metadata or {})}, ensure_ascii=False),
            "updated_at": now,
        }
        db.execute(
            "UPDATE machines SET name=?, manufacturer=?, model=?, serial_number=?,"
            " metadata_json=?, updated_at=? WHERE id=?",
            (merged["name"], merged["manufacturer"], merged["model"], merged["serial_number"],
             merged["metadata_json"], now, existing["id"]))
        return db.query_one("SELECT * FROM machines WHERE id = ?", (existing["id"],))

    row = {"id": new_id("mach"), "name": name, "manufacturer": manufacturer, "model": model,
           "serial_number": serial_number,
           "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
           "created_at": now, "updated_at": now}
    db.insert("machines", row)
    return row


def list_machines() -> List[Dict[str, Any]]:
    return db.query("SELECT * FROM machines ORDER BY updated_at DESC")


# -------------------------------------------------------------------- jobs

def create_job(title: Optional[str] = None, machine_id: Optional[str] = None,
               status: str = "open", summary: Optional[str] = None) -> Dict[str, Any]:
    now = utc_now()
    row = {"id": new_id("job"), "machine_id": machine_id,
           "title": (title or "Untitled job").strip()[:160],
           "status": status, "summary": summary, "created_at": now, "updated_at": now}
    db.insert("jobs", row)
    return row


def list_jobs(machine_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    if machine_id:
        return db.query(
            "SELECT * FROM jobs WHERE machine_id = ? ORDER BY updated_at DESC LIMIT ?",
            (machine_id, limit))
    return db.query("SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,))


def get_job(job_id: str) -> Dict[str, Any]:
    row = db.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not row:
        raise NotFound("no such job", job_id=job_id)
    return row


def update_job(job_id: str, **fields: Any) -> Dict[str, Any]:
    get_job(job_id)
    allowed = {k: v for k, v in fields.items()
               if k in {"title", "status", "summary", "machine_id"} and v is not None}
    if allowed:
        sets = ", ".join(f"{k} = ?" for k in allowed)
        db.execute(f"UPDATE jobs SET {sets}, updated_at = ? WHERE id = ?",
                   [*allowed.values(), utc_now(), job_id])
    return get_job(job_id)


def job_history(job_id: str) -> Dict[str, Any]:
    """Everything worth knowing when the technician reopens this machine."""
    job = get_job(job_id)
    machine = None
    if job["machine_id"]:
        machine = db.query_one("SELECT * FROM machines WHERE id = ?", (job["machine_id"],))
    inspections = db.query(
        "SELECT * FROM inspections WHERE job_id = ? ORDER BY started_at", (job_id,))
    ids = [i["id"] for i in inspections]
    findings: List[Dict[str, Any]] = []
    measurements: List[Dict[str, Any]] = []
    if ids:
        marks = ",".join("?" for _ in ids)
        findings = db.query(
            f"SELECT * FROM findings WHERE inspection_id IN ({marks}) ORDER BY created_at", ids)
        measurements = db.query(
            f"SELECT * FROM measurements WHERE inspection_id IN ({marks}) ORDER BY created_at", ids)
    memories = db.query(
        "SELECT * FROM memories WHERE job_id = ? ORDER BY updated_at DESC", (job_id,))
    prior_jobs = []
    if job["machine_id"]:
        prior_jobs = db.query(
            "SELECT id, title, status, summary, created_at FROM jobs"
            " WHERE machine_id = ? AND id != ? ORDER BY created_at DESC LIMIT 5",
            (job["machine_id"], job_id))
    return {"job": job, "machine": machine, "inspections": inspections,
            "findings": findings, "measurements": measurements, "memories": memories,
            "prior_jobs_on_machine": prior_jobs}


# ------------------------------------------------------------- inspections

def start_inspection(job_id: str, mode: str) -> Dict[str, Any]:
    get_job(job_id)
    row = {"id": new_id("insp"), "job_id": job_id, "mode": mode,
           "started_at": utc_now(), "ended_at": None, "summary": None}
    db.insert("inspections", row)
    return row


def end_inspection(inspection_id: str, summary: Optional[str] = None) -> Dict[str, Any]:
    db.execute("UPDATE inspections SET ended_at = ?, summary = COALESCE(?, summary) WHERE id = ?",
               (utc_now(), summary, inspection_id))
    row = db.query_one("SELECT * FROM inspections WHERE id = ?", (inspection_id,))
    if not row:
        raise NotFound("no such inspection", inspection_id=inspection_id)
    return row


def save_finding(inspection_id: str, description: str, type: Optional[str] = None,
                 confidence: Optional[float] = None,
                 source: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not db.query_one("SELECT id FROM inspections WHERE id = ?", (inspection_id,)):
        raise NotFound("no such inspection", inspection_id=inspection_id)
    if not (description or "").strip():
        raise ValidationFailed("a finding needs a description")
    row = {"id": new_id("find"), "inspection_id": inspection_id, "type": type,
           "description": description.strip(), "confidence": confidence,
           "source_json": json.dumps(source or {}, ensure_ascii=False), "created_at": utc_now()}
    db.insert("findings", row)
    return row


def save_measurement(inspection_id: str, name: str, value: Optional[float],
                     unit: Optional[str] = None, source: str = "technician") -> Dict[str, Any]:
    if not db.query_one("SELECT id FROM inspections WHERE id = ?", (inspection_id,)):
        raise NotFound("no such inspection", inspection_id=inspection_id)
    if not (name or "").strip():
        raise ValidationFailed("a measurement needs a name")
    if value is None:
        # §18: never fabricate measurements — refuse rather than store a placeholder.
        raise ValidationFailed(
            "a measurement needs a value taken by the technician or an instrument; "
            "nothing is stored without one")
    row = {"id": new_id("meas"), "inspection_id": inspection_id, "name": name.strip(),
           "value": float(value), "unit": unit, "source": source, "created_at": utc_now()}
    db.insert("measurements", row)
    return row


# ---------------------------------------------------------------- memories

async def save_memory(memory_type: str, content: str, confidence: Optional[float] = None,
                      source: Optional[Dict[str, Any]] = None, job_id: Optional[str] = None,
                      user_id: Optional[str] = None, confirmed: bool = False) -> Dict[str, Any]:
    verdict = WritePolicy.evaluate(memory_type, content, confidence, source, confirmed,
                                   job_id=job_id)
    if not verdict["store"]:
        log.info("memory refused (%s): %s", verdict["reason"], preview(content, 60))
        return {"stored": False, **verdict}

    now = utc_now()
    row = {"id": new_id("mem"), "user_id": user_id or ensure_user()["id"], "job_id": job_id,
           "memory_type": memory_type, "content": content.strip(),
           "confidence": confidence,
           "source_json": json.dumps({**(source or {}), "confirmed": confirmed},
                                     ensure_ascii=False),
           "created_at": now, "updated_at": now}
    db.insert("memories", row)

    embedder = registry.embedding()
    if embedder.is_ready():
        try:
            vec = (await embedder.embed([row["content"]]))[0]
            vs.add(vs.MEMORY, row["id"], vec, embedder.model_id)
        except Exception as exc:
            log.warning("memory embedding failed: %s", type(exc).__name__)
    return {"stored": True, "memory": row, "reason": verdict["reason"]}


def list_memories(job_id: Optional[str] = None, memory_type: Optional[str] = None,
                  limit: int = 100) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM memories WHERE 1=1"
    params: List[Any] = []
    if job_id:
        sql += " AND job_id = ?"
        params.append(job_id)
    if memory_type:
        sql += " AND memory_type = ?"
        params.append(memory_type)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    return db.query(sql, params)


def forget_memory(memory_id: str) -> Dict[str, Any]:
    if not db.query_one("SELECT id FROM memories WHERE id = ?", (memory_id,)):
        raise NotFound("no such memory", memory_id=memory_id)
    vs.delete_for(vs.MEMORY, [memory_id])
    db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    return {"memory_id": memory_id, "deleted": True}


# ------------------------------------------------------------- tool calls

def log_tool_call(conversation_id: Optional[str], tool_name: str, arguments: Dict[str, Any],
                  result: Dict[str, Any], duration_ms: float) -> str:
    """Audit trail.  Results are summarised, never dumped whole (§24)."""
    row_id = new_id("tc")
    db.insert("tool_calls", {
        "id": row_id, "conversation_id": conversation_id, "tool_name": tool_name,
        "arguments_json": json.dumps(_summarise(arguments), ensure_ascii=False)[:4000],
        "result_json": json.dumps(_summarise(result), ensure_ascii=False)[:8000],
        "duration_ms": int(duration_ms), "created_at": utc_now(),
    })
    return row_id


def _summarise(value: Any, depth: int = 0) -> Any:
    if depth > 3:
        return "<deep>"
    if isinstance(value, str):
        return preview(value, 300)
    if isinstance(value, dict):
        return {k: _summarise(v, depth + 1) for k, v in list(value.items())[:25]}
    if isinstance(value, (list, tuple)):
        head = [_summarise(v, depth + 1) for v in list(value)[:8]]
        if len(value) > 8:
            head.append(f"<+{len(value) - 8} more>")
        return head
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    return value


def recent_tool_calls(conversation_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    return db.query(
        "SELECT * FROM tool_calls WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
        (conversation_id, limit))

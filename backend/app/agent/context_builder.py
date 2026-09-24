"""Context assembly (§2, §16).

Builds the message list the reasoning model sees, in the priority order the
specification fixes:

    1. current job context
    2. the technician's documents
    3. local memory / RAG
    4. web search, only when enabled

It also decides which images to send.  §7: "The VLM should be given only the
useful images/results, not every image repeatedly" — so the newest frames win,
capped, and a document page opened by a tool counts as one of them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.agent.prompts import evidence_block, system_prompt
from app.knowledge import web_search as ws
from app.logging_setup import get_logger
from app.memory import memory_service as M
from app.memory import sqlite as db
from app.models.base import ImageRef
from app.util import preview

log = get_logger(__name__)

MAX_HISTORY_MESSAGES = 12
MAX_IMAGES = 3


def job_context(job_id: Optional[str]) -> Dict[str, Any]:
    if not job_id:
        return {}
    try:
        h = M.job_history(job_id)
    except Exception:
        return {}
    machine = h.get("machine") or {}
    return {
        "job_id": job_id,
        "job_title": h["job"].get("title"),
        "job_status": h["job"].get("status"),
        "machine": machine.get("name"),
        "machine_model": machine.get("model"),
        "machine_serial": machine.get("serial_number"),
        "open_findings": len(h.get("findings") or []),
        "recorded_measurements": [
            {"name": m["name"], "value": m["value"], "unit": m.get("unit")}
            for m in (h.get("measurements") or [])[-6:]
        ],
    }


def conversation_history(conversation_id: str) -> List[Dict[str, str]]:
    rows = M.get_messages(conversation_id, limit=MAX_HISTORY_MESSAGES)
    out: List[Dict[str, str]] = []
    for r in rows:
        content = r["content"]
        if r["role"] == "assistant" and len(content) > 1200:
            content = content[:1200] + "…"
        out.append({"role": r["role"], "content": content})
    return out


def resolve_images(image_ids: Sequence[str]) -> List[ImageRef]:
    if not image_ids:
        return []
    marks = ",".join("?" for _ in image_ids)
    rows = db.query(f"SELECT * FROM images WHERE id IN ({marks})", list(image_ids))
    order = {v: i for i, v in enumerate(image_ids)}
    rows.sort(key=lambda r: order.get(r["id"], 0))
    refs: List[ImageRef] = []
    for r in rows[-MAX_IMAGES:]:
        if Path(r["path"]).exists():
            refs.append(ImageRef(id=r["id"], path=r["path"], width=r["width"] or 0,
                                 height=r["height"] or 0,
                                 mime_type=r["mime_type"] or "image/jpeg",
                                 source=r["source"] or "photo"))
    return refs


def build(question: str, conversation_id: str, evidence: Dict[str, Any],
          image_ids: Sequence[str] = (), job_id: Optional[str] = None,
          mode: str = "normal", profile: Optional[Dict[str, Any]] = None,
          tool_schemas: Optional[Sequence[Dict[str, Any]]] = None,
          document_count: int = 0, web_requested: bool = False,
          round_index: int = 0) -> Dict[str, Any]:
    jc = job_context(job_id)

    preamble: List[str] = []
    if jc:
        bits = [f"Job: {jc.get('job_title')}"]
        if jc.get("machine"):
            bits.append(f"Machine: {jc['machine']}"
                        + (f" ({jc['machine_model']})" if jc.get("machine_model") else ""))
        if jc.get("machine_serial"):
            bits.append(f"Serial: {jc['machine_serial']}")
        for m in jc.get("recorded_measurements") or []:
            bits.append(f"Recorded {m['name']}: {m['value']} {m.get('unit') or ''}".strip())
        preamble.append("Current job context — " + "; ".join(bits))
    preamble.append(f"Mode: {'live camera' if mode == 'live' else 'photo / chat'}.")
    preamble.append(f"Documents in the local vault: {document_count}.")
    provider = ws.get_provider()
    preamble.append(
        "Web research: enabled for this turn." if (web_requested and provider.enabled)
        else "Web research: off — answer from local knowledge and say when something "
             "would need looking up.")
    if image_ids:
        preamble.append(f"{len(image_ids)} image(s) attached to this turn.")

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt(tool_schemas, profile)},
        {"role": "system", "content": "\n".join(preamble)},
    ]
    messages.extend(conversation_history(conversation_id))
    if evidence:
        messages.append({"role": "system", "content": evidence_block(evidence)})
    messages.append({"role": "user", "content": question})

    images = resolve_images(list(image_ids))
    page = evidence.get("get_document_page") or {}
    if page.get("image_path") and Path(page["image_path"]).exists():
        images = images[: MAX_IMAGES - 1] + [ImageRef(
            id=f"{page['document_id']}_p{page['page_number']}",
            path=page["image_path"], mime_type="image/png", source="document_page")]

    log.debug("context: %d message(s), %d image(s), evidence=%s",
              len(messages), len(images), sorted(evidence))

    return {
        "messages": messages,
        "images": images,
        "context": {
            "conversation_id": conversation_id,
            "job_id": job_id,
            "mode": mode,
            "round": round_index,
            "evidence": evidence,
            "image_ids": list(image_ids),
            "document_count": document_count,
            "web_search_requested": bool(web_requested and provider.enabled),
            "job": jc,
        },
    }

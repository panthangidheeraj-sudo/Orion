"""The agent loop (§2).

    build context -> decide whether tools are needed -> call tools ->
    collect structured evidence -> reason -> ask a targeted question OR call
    another tool -> answer -> persist useful memory

SEE → RETRIEVE → REASON → VERIFY → GUIDE → REMEMBER.

The backend owns this loop.  The front-end sends a question and receives a
finished, safety-reviewed answer; it never decides which model runs or in
what order.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence

from app.agent import context_builder, safety
from app.agent import conversation as small_talk
from app.agent.tool_registry import registry as tool_registry
from app.config import settings
from app.errors import ModelUnavailable
from app.knowledge import web_search as ws
from app.logging_setup import get_logger
from app.memory import memory_service as M
from app.memory import sqlite as db
from app.metrics import collector as metrics
from app.models.heuristic import extract_measurements
from app.models.registry import registry as models
from app.util import ms, preview, timed, utc_now

log = get_logger(__name__)

# Tools the model may invoke on its own.  Writes are deliberately excluded
# from the default set: a memory or a measurement is recorded when the
# technician confirms it, through the explicit endpoints, not because the
# model felt like it mid-sentence (§13).
READ_TOOLS = [
    "vision_detect", "vision_classify", "vision_segment", "vision_track", "ocr_extract",
    "search_documents", "get_document_page", "get_document_metadata", "list_documents",
    "search_memory", "get_job_history",
    "ask_user", "create_inspection_checklist",
]
WEB_TOOLS = ["web_search", "fetch_web_source"]
WRITE_TOOLS = ["save_memory", "save_finding", "save_measurement", "create_service_report"]

CONFIRMED = re.compile(
    r"\b(confirmed|verified|i (?:replaced|fitted|fixed|repaired|measured|tightened|cleaned)|"
    r"we (?:replaced|fitted|fixed|repaired|measured)|turned out to be|it was the|"
    r"after replacing|now reads|resolved|working again)\b", re.I)


def allowed_tools(web: bool = False, writes: bool = False) -> List[str]:
    allow = list(READ_TOOLS)
    if web and ws.get_provider().enabled:
        allow += WEB_TOOLS
    if writes:
        allow += WRITE_TOOLS
    return allow


class Orchestrator:
    async def ask(
        self,
        question: str,
        conversation_id: Optional[str] = None,
        image_ids: Sequence[str] = (),
        job_id: Optional[str] = None,
        inspection_id: Optional[str] = None,
        mode: str = "normal",
        web: bool = False,
        profile: Optional[Dict[str, Any]] = None,
        allow_writes: bool = False,
        persist: bool = True,
    ) -> Dict[str, Any]:
        started_ms = ms()
        conversation = M.ensure_conversation(conversation_id, title=preview(question, 60))
        cid = conversation["id"]
        if persist:
            M.add_message(cid, "user", question,
                          {"image_ids": list(image_ids), "mode": mode, "job_id": job_id})

        allow = allowed_tools(web, allow_writes)
        schemas = tool_registry.schemas(allow=allow, online_allowed=web)
        doc_count = (db.query_one("SELECT COUNT(*) AS n FROM documents") or {}).get("n", 0)

        # A greeting is not a diagnostic request. Answer it like a person and
        # stop — no retrieval, no tool calls, no NPU inference (§8's efficiency
        # argument applies to idle chat too).
        #
        # Nobody attaches a photograph to say hello, so an image on the turn
        # settles it: "what is this?" over a picture of a bearing housing is
        # work, whatever the words look like on their own.
        intent = None if image_ids else small_talk.classify(question)
        if intent:
            return self._conversational(
                intent, conversation_id=cid, question=question, job_id=job_id,
                mode=mode, doc_count=doc_count, started_ms=started_ms, persist=persist)

        evidence: Dict[str, Any] = {}
        trail: List[Dict[str, Any]] = []
        reasoner = models.reasoning()
        result: Dict[str, Any] = {}
        degraded: List[str] = []

        for round_index in range(settings.agent_max_tool_rounds):
            built = context_builder.build(
                question, cid, evidence, image_ids=image_ids, job_id=job_id,
                mode=mode, profile=profile, tool_schemas=schemas,
                document_count=doc_count, web_requested=web, round_index=round_index)
            built["context"]["inspection_id"] = inspection_id

            try:
                with timed() as reason_t:
                    result = await reasoner.generate(
                        built["messages"], images=built["images"],
                        tools=schemas, context=built["context"])
                metrics.record_reasoning(reason_t["ms"])
            except ModelUnavailable as exc:
                log.warning("reasoning unavailable: %s", exc.reason)
                return self._no_model_response(cid, question, evidence, trail,
                                               exc.to_dict(), ms() - started_ms,
                                               persist)

            calls = [c for c in (result.get("tool_calls") or []) if c.get("tool")]
            if not calls:
                break

            outcomes = await self._run_tools(calls, built["context"], allow, cid)
            for name, payload in outcomes:
                trail.append(payload["trail"])
                evidence[name] = payload["result"]
                if payload["result"].get("degraded"):
                    degraded.append(name)

        elapsed = ms() - started_ms
        metrics.record_response(elapsed)
        return self._finalise(
            conversation=conversation, question=question, result=result,
            evidence=evidence, trail=trail, image_ids=list(image_ids), job_id=job_id,
            inspection_id=inspection_id, mode=mode, degraded=degraded,
            total_ms=round(elapsed, 2), persist=persist)

    # -------------------------------------------------------- conversation
    def _conversational(self, intent, conversation_id, question, job_id, mode,
                        doc_count, started_ms, persist) -> Dict[str, Any]:
        """A chat turn: short reply, none of the diagnostic furniture."""
        job_title = None
        if job_id:
            try:
                job_title = M.get_job(job_id).get("title")
            except Exception:
                job_title = None

        health = models.reasoning().health()
        turns = len(M.get_messages(conversation_id, limit=6))
        built = small_talk.reply(intent, {
            "document_count": doc_count,
            "job_title": job_title,
            "has_history": turns > 1,
            "display_name": (M.ensure_user() or {}).get("display_name"),
            "engine": {"provider": health.provider, "model_id": health.model_id,
                       "accelerator": health.accelerator, "npu": health.npu,
                       "synthetic": health.synthetic},
        })

        # No safety review here: this is our own fixed copy, not model output,
        # and it describes no procedure. Running the hazard scanner over it
        # would staple "Isolate the supply" onto the word "hello".
        elapsed = ms() - started_ms
        metrics.record_response(elapsed)
        log.info("conversational turn (%s) in %.1f ms — no tools, no retrieval",
                 intent, elapsed)

        response = {
            "conversation_id": conversation_id,
            "message_id": None,
            "text": built["text"],
            "sections": [],
            "notice": None,
            "question": None,
            "refs": [],
            "evidence_keys": [],
            "work_trail": [],
            "confidence": None,
            "confidence_label": None,
            "hazards": [],
            "safety_notes": [],
            "unverified_figures": [],
            "degraded_tools": [],
            "memory": None,
            "follow_ups": built["meta"]["follow_ups"],
            "conversational": True,
            "intent": intent,
            "mode": mode,
            "job_id": job_id,
            "inspection_id": None,
            "model": {"provider": health.provider, "model_id": health.model_id,
                      "accelerator": health.accelerator, "npu": health.npu,
                      "synthetic": health.synthetic},
            "duration_ms": round(elapsed, 2),
            "created_at": utc_now(),
        }
        if persist:
            response["message_id"] = M.add_message(
                conversation_id, "assistant", built["text"],
                {"conversational": True, "intent": intent,
                 "follow_ups": response["follow_ups"]})["id"]
        return response

    # ------------------------------------------------------------- tool run
    async def _run_tools(self, calls: Sequence[Dict[str, Any]], context: Dict[str, Any],
                         allow: Sequence[str], conversation_id: str):
        # Reads are independent, so they run together; one slow manual search
        # should not hold up the detector.
        tasks = [tool_registry.call(c["tool"], c.get("arguments") or {},
                                    context=context, allow=allow) for c in calls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        out = []
        for call, res in zip(calls, results):
            name = call["tool"]
            if isinstance(res, BaseException):
                res = {"ok": False, "tool": name, "error": "TOOL_ERROR",
                       "reason": f"{type(res).__name__}: {res}", "duration_ms": 0.0}
            M.log_tool_call(conversation_id, name, call.get("arguments") or {},
                            res, res.get("duration_ms", 0.0))
            out.append((name, {
                "result": res,
                "trail": {"tool": name, "ok": res.get("ok", False),
                          "duration_ms": res.get("duration_ms", 0.0),
                          "summary": _summarise_tool(name, res)},
            }))
            log.info("tool %s ok=%s in %.0f ms", name, res.get("ok"), res.get("duration_ms", 0))
        return out

    # ------------------------------------------------------------- finalise
    def _finalise(self, conversation, question, result, evidence, trail, image_ids,
                  job_id, inspection_id, mode, degraded, total_ms, persist):
        text = result.get("text") or ""
        sections = result.get("sections") or _sections_from_text(text)
        meta = result.get("meta") or {}

        verdict = safety.review(text, evidence=evidence, user_text=question, sections=sections)

        notice = None
        if verdict["hazard_notices"]:
            notice = {"level": "safety", "title": "Before you touch it",
                      "items": verdict["hazard_notices"],
                      "note": verdict["professional_note"]}
        elif verdict["unverified_figures"]:
            notice = {"level": "need", "title": "Figures to confirm",
                      "items": verdict["unverified_figures"]}

        question_asked = (evidence.get("ask_user") or {}).get("question")
        refs = meta.get("refs") or _refs_from_evidence(evidence)
        confidence = meta.get("confidence")
        if confidence is None:
            confidence = _confidence_from_evidence(evidence)
        remembered = self._remember(question, evidence, job_id, conversation["id"])

        reasoner_health = models.reasoning().health()
        response = {
            "conversation_id": conversation["id"],
            "message_id": None,
            "text": verdict["text"],
            "sections": sections,
            "notice": notice,
            "question": question_asked,
            "refs": refs,
            "evidence_keys": sorted(evidence),
            "work_trail": trail,
            "confidence": confidence,
            "confidence_label": meta.get("confidence_label") or _label(confidence),
            "hazards": [h["key"] for h in verdict["hazards"]],
            "safety_notes": verdict["notes"],
            "unverified_figures": verdict["unverified_figures"],
            "degraded_tools": sorted(set(degraded)),
            "memory": remembered,
            "follow_ups": _follow_ups(evidence, verdict, question),
            "mode": mode,
            "job_id": job_id,
            "inspection_id": inspection_id,
            "model": {
                "provider": reasoner_health.provider,
                "model_id": reasoner_health.model_id,
                "accelerator": reasoner_health.accelerator,
                "npu": reasoner_health.npu,
                "synthetic": reasoner_health.synthetic,
            },
            "duration_ms": total_ms,
            "created_at": utc_now(),
        }
        if persist:
            stored = M.add_message(
                conversation["id"], "assistant", verdict["text"],
                {k: response[k] for k in
                 ("sections", "notice", "refs", "confidence", "confidence_label",
                  "work_trail", "hazards", "degraded_tools", "model", "question")})
            response["message_id"] = stored["id"]
        return response

    def _no_model_response(self, cid, question, evidence, trail, error, total_ms, persist):
        """§25: say exactly what is missing rather than producing something anyway."""
        text = ("No reasoning model is available on this machine, so I will not attempt a "
                "diagnosis. Export a VLM into data/models/ or start a local model server, "
                "then ask again. Everything else — documents, memory and the job record — "
                "still works.")
        response = {
            "conversation_id": cid, "message_id": None, "text": text,
            "sections": [{"kind": "observed", "title": "Status", "items": [text]}],
            "notice": {"level": "error", "title": "Reasoning model unavailable",
                       "items": [error.get("reason", "")]},
            "error": error, "refs": [], "evidence_keys": sorted(evidence),
            "work_trail": trail, "confidence": 0.0, "confidence_label": "Needs evidence",
            "hazards": [], "safety_notes": [], "unverified_figures": [],
            "degraded_tools": [], "memory": None, "follow_ups": [],
            "duration_ms": total_ms, "created_at": utc_now(),
        }
        if persist:
            response["message_id"] = M.add_message(cid, "assistant", text,
                                                   {"error": error})["id"]
        return response

    # -------------------------------------------------------------- REMEMBER
    def _remember(self, question: str, evidence: Dict[str, Any], job_id: Optional[str],
                  conversation_id: str) -> Optional[Dict[str, Any]]:
        """Only confirmed facts the technician stated become durable (§13)."""
        if not CONFIRMED.search(question or ""):
            return None
        measurements = extract_measurements(question)
        content = preview(question.strip(), 400)
        candidate = {
            "memory_type": "result" if measurements else "repair_action",
            "content": content,
            "confidence": 0.9,
            "confirmed": True,
            "source": {"origin": "technician_statement", "conversation_id": conversation_id},
        }
        verdict = M.WritePolicy.evaluate(
            candidate["memory_type"], candidate["content"], candidate["confidence"],
            candidate["source"], True, job_id=job_id)
        if not verdict["store"]:
            return {"stored": False, "reason": verdict["reason"]}
        return {"stored": False, "pending_confirmation": True, "candidate": candidate,
                "reason": "ready to store — confirm from the client to write it durably"}

    # --------------------------------------------------------------- stream
    async def stream(self, question: str, **kw) -> AsyncIterator[Dict[str, Any]]:
        """Server-sent events: work trail first, then the answer.

        Tool rounds happen before any text exists, so the client sees what the
        agent is doing rather than a spinner.
        """
        started = ms()
        first_token_sent = False
        yield {"type": "start", "at": utc_now()}
        reasoner = models.reasoning()
        yield {"type": "model", "provider": reasoner.health().provider,
               "model_id": reasoner.model_id, "synthetic": reasoner.health().synthetic,
               "accelerator": reasoner.health().accelerator, "npu": reasoner.health().npu}
        result = await self.ask(question, **kw)
        for step in result["work_trail"]:
            yield {"type": "step", **step}
        for chunk in _chunk_text(result["text"]):
            if not first_token_sent:
                metrics.record_first_token(ms() - started)
                first_token_sent = True
            yield {"type": "text", "value": chunk}
            await asyncio.sleep(0)
        yield {"type": "done", "result": result}


# ---------------------------------------------------------------- helpers

def _chunk_text(text: str, size: int = 120) -> List[str]:
    words, out, buf = (text or "").split(" "), [], ""
    for w in words:
        if len(buf) + len(w) + 1 > size:
            out.append(buf)
            buf = w
        else:
            buf = f"{buf} {w}".strip()
    if buf:
        out.append(buf)
    return out


def _summarise_tool(name: str, res: Dict[str, Any]) -> str:
    if not res.get("ok"):
        return res.get("reason", "failed")
    if name == "vision_detect":
        n = len(res.get("detections") or [])
        return f"{n} object(s) detected" if n else "no objects detected"
    if name == "ocr_extract":
        n = len(res.get("text_regions") or [])
        return f"{n} text region(s) read" if n else "no text read"
    if name == "search_documents":
        return f"{res.get('count', 0)} passage(s) from your documents"
    if name == "get_document_page":
        return f"opened {res.get('filename')} page {res.get('page_number')}"
    if name == "search_memory":
        return f"{res.get('count', 0)} memory record(s)"
    if name == "get_job_history":
        return f"{len(res.get('findings') or [])} past finding(s)"
    if name == "web_search":
        return f"{res.get('count', 0)} web source(s)"
    if name == "ask_user":
        return "question prepared for the technician"
    return "ok"


def _sections_from_text(text: str) -> List[Dict[str, Any]]:
    """Split a free-form model answer on the §18 headings, if it used them."""
    if not text:
        return []
    kinds = {"observed": "observed", "likely causes": "inferred", "likely": "inferred",
             "evidence": "ref", "what to test next": "next", "next steps": "next",
             "needs confirmation": "measure", "safety": "observed"}
    sections: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for line in text.splitlines():
        stripped = line.strip().rstrip(":")
        key = stripped.lower()
        if key in kinds and len(stripped) < 40:
            current = {"kind": kinds[key], "title": stripped, "items": []}
            sections.append(current)
            continue
        if current is not None and stripped:
            current["items"].append(stripped.lstrip("-• ").strip())
    return [s for s in sections if s["items"]]


def _refs_from_evidence(evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for r in ((evidence.get("search_documents") or {}).get("results") or [])[:4]:
        refs.append({"kind": "document", "document_id": r["document_id"],
                     "filename": r["filename"], "page": r["page_start"],
                     "score": r["score"], "excerpt": r["content"][:220]})
    page = evidence.get("get_document_page") or {}
    if page.get("page_number"):
        refs.append({"kind": "document_page", "document_id": page["document_id"],
                     "filename": page.get("filename"), "page": page["page_number"]})
    for m in ((evidence.get("search_memory") or {}).get("memories") or [])[:3]:
        refs.append({"kind": "memory", "memory_id": m["id"],
                     "memory_type": m["memory_type"], "excerpt": m["content"][:180]})
    for w in ((evidence.get("web_search") or {}).get("results") or [])[:3]:
        refs.append({"kind": "web", "title": w.get("title"), "url": w.get("url"),
                     "domain": w.get("domain"), "retrieved_at": w.get("retrieved_at")})
    return refs


def _confidence_from_evidence(evidence: Dict[str, Any]) -> float:
    score = 0.2
    if (evidence.get("vision_detect") or {}).get("detections"):
        score += 0.15
    if (evidence.get("ocr_extract") or {}).get("text_regions"):
        score += 0.12
    if (evidence.get("search_documents") or {}).get("results"):
        score += 0.25
    if (evidence.get("search_memory") or {}).get("memories"):
        score += 0.08
    if (evidence.get("get_job_history") or {}).get("findings"):
        score += 0.08
    return round(min(score, 0.9), 2)


def _label(c: Optional[float]) -> str:
    c = c or 0.0
    return ("Well supported" if c >= 0.7 else "Partly supported" if c >= 0.5
            else "Weak evidence" if c >= 0.33 else "Needs evidence")


def _follow_ups(evidence: Dict[str, Any], verdict: Dict[str, Any], question: str) -> List[str]:
    out: List[str] = []
    docs = (evidence.get("search_documents") or {}).get("results") or []
    if docs:
        out.append(f"Open {docs[0]['filename']} page {docs[0]['page_start']}")
    if verdict["hazards"]:
        out.append("Show me the isolation steps for this machine")
    if not docs:
        out.append("Upload the manual for this machine")
    out.append("Build an inspection checklist")
    return out[:4]


orchestrator = Orchestrator()

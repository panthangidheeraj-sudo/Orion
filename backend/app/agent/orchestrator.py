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

from app.agent import context_builder, router, safety
from app.agent.prompts import conversation_prompt
from app.agent.measurements import extract_measurements
from app.agent.tool_registry import registry as tool_registry
from app.config import settings
from app.errors import ModelUnavailable
from app.knowledge import web_search as ws
from app.logging_setup import get_logger
from app.memory import memory_service as M
from app.memory import sqlite as db
from app.metrics import collector as metrics
from app.models.qwen_vl import parse_tool_calls
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


FALLBACK_TEXT = "I’m here. Tell me a little more about what you need."
FALLBACK_SAFETY_TEXT = ("That sounds dangerous — please get yourself safe first; the steps are "
                        "below. Once everything is isolated, tell me what you saw.")


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
        attachments: Sequence[Dict[str, Any]] = (),
    ) -> Dict[str, Any]:
        """One turn.

            SAFETY GATE  deterministic, independent, runs first, only adds
            ROUTER       the reasoning model decides: conversation / technical / ambiguous
            then either  a plain conversational reply
            or           SEE → RETRIEVE → REASON → VERIFY → GUIDE → REMEMBER
        """
        started_ms = ms()
        conversation = M.ensure_conversation(conversation_id, title=preview(question, 60))
        cid = conversation["id"]
        attachments = [dict(a) for a in attachments][:8]
        if persist:
            M.add_message(cid, "user", question,
                          {"image_ids": list(image_ids), "mode": mode, "job_id": job_id,
                           "attachments": attachments})

        doc_count = (db.query_one("SELECT COUNT(*) AS n FROM documents") or {}).get("n", 0)
        history = context_builder.conversation_history(cid, current=question)
        job = context_builder.job_context(job_id)

        # 1. The independent safety gate. Deterministic on purpose, and the
        #    only thing that still works with no model at all.
        gate = safety.input_gate(question)

        # 2. The router: meaning, from the model — never from keywords.
        models.refresh_if_unavailable("reasoning")
        reasoner = models.reasoning()
        seen = [{"kind": "image"} for _ in image_ids] + attachments
        decision = await router.route(reasoner, question, history, mode, seen, profile,
                                      job.get("job_title"))
        if decision.available and decision.requires_safety_gate and not gate:
            gate = dict(safety.GENERIC_CAUTION)

        if not decision.available:
            return self._fallback(cid, question, gate, decision, mode, job_id,
                                  started_ms, persist)
        if decision.intent in ("conversation", "ambiguous"):
            return await self._converse(decision, cid, question, history, image_ids,
                                        profile, gate, mode, job_id, started_ms, persist)

        # 3. Technical: the full workflow.
        allow = allowed_tools(web, allow_writes)
        schemas = tool_registry.schemas(allow=allow, online_allowed=web)
        evidence: Dict[str, Any] = {}
        trail: List[Dict[str, Any]] = []
        result: Dict[str, Any] = {}
        degraded: List[str] = []

        def _absorb(outcomes):
            for name, payload in outcomes:
                trail.append(payload["trail"])
                evidence[name] = payload["result"]
                if payload["result"].get("degraded"):
                    degraded.append(name)

        # SEE + RETRIEVE up front, so the evidence is there whatever the model's
        # tool-calling ability. The model may ask for more below.
        seed = _seed_calls(question, history, image_ids, doc_count, job_id)
        if seed:
            base_ctx = {"conversation_id": cid, "job_id": job_id, "image_ids": list(image_ids),
                        "mode": mode, "evidence": evidence}
            _absorb(await self._run_tools(seed, base_ctx, allow, cid))

        for round_index in range(settings.agent_max_tool_rounds):
            built = context_builder.build(
                question, cid, evidence, image_ids=image_ids, job_id=job_id,
                mode=mode, profile=profile, tool_schemas=schemas,
                document_count=doc_count, web_requested=web, round_index=round_index)
            built["context"]["inspection_id"] = inspection_id
            built["context"]["purpose"] = "technical"

            try:
                with timed() as reason_t:
                    result = await reasoner.generate(
                        built["messages"], images=built["images"],
                        tools=schemas, context=built["context"])
                metrics.record_reasoning(reason_t["ms"])
            except ModelUnavailable as exc:
                log.warning("reasoning unavailable mid-turn: %s", exc.reason)
                return self._fallback(cid, question, gate, router.RouteDecision(
                    available=False, failure=exc.reason), mode, job_id, started_ms, persist)

            calls = [c for c in (result.get("tool_calls") or []) if c.get("tool")]
            if not calls:
                break
            _absorb(await self._run_tools(calls, built["context"], allow, cid))

        elapsed = ms() - started_ms
        metrics.record_response(elapsed)
        return self._finalise(
            conversation=conversation, question=question, result=result,
            evidence=evidence, trail=trail, image_ids=list(image_ids), job_id=job_id,
            inspection_id=inspection_id, mode=mode, degraded=degraded,
            total_ms=round(elapsed, 2), persist=persist, gate=gate, decision=decision)

    # --------------------------------------------------------- shared shape
    @staticmethod
    def _model_info() -> Dict[str, Any]:
        h = models.reasoning().health()
        return {"provider": h.provider, "model_id": h.model_id, "accelerator": h.accelerator,
                "npu": h.npu and not h.hosted, "synthetic": h.synthetic, "hosted": h.hosted}

    def _plain(self, cid, text, kind, gate, decision, mode, job_id, started_ms, persist,
               extra_meta: Optional[Dict[str, Any]] = None, record: bool = True) -> Dict[str, Any]:
        """A reply with none of the diagnostic furniture: no sections, no
        confidence, no work trail, no suggestion chips. A safety notice from the
        gate is the only thing that can ride along — and it goes first."""
        elapsed = ms() - started_ms
        if record:
            metrics.record_response(elapsed)
        notice = _public_notice(gate)
        response = {
            "conversation_id": cid, "message_id": None, "text": text,
            "sections": [], "notice": notice, "question": None, "refs": [],
            "evidence_keys": [], "work_trail": [], "confidence": None,
            "confidence_label": None, "hazards": list((gate or {}).get("hazards") or []),
            "safety_notes": [], "unverified_figures": [], "degraded_tools": [],
            "memory": None, "follow_ups": [],
            "conversational": True, "kind": kind,
            "intent": decision.intent, "route": decision.public(),
            "engine_available": decision.available,
            "mode": mode, "job_id": job_id, "inspection_id": None,
            "model": self._model_info(),
            "duration_ms": round(elapsed, 2), "created_at": utc_now(),
        }
        if persist:
            response["message_id"] = M.add_message(
                cid, "assistant", text,
                {"conversational": True, "kind": kind, "intent": decision.intent,
                 "notice": notice, **(extra_meta or {})})["id"]
        return response

    def _fallback(self, cid, question, gate, decision, mode, job_id, started_ms, persist):
        """No model to understand the message: say only what is safe to say."""
        log.info("router unavailable (%s) — plain fallback", decision.failure)
        text = FALLBACK_SAFETY_TEXT if gate else FALLBACK_TEXT
        return self._plain(cid, text, "fallback", gate, decision, mode, job_id, started_ms,
                           persist, {"engine_available": False})

    async def _converse(self, decision, cid, question, history, image_ids, profile, gate,
                        mode, job_id, started_ms, persist) -> Dict[str, Any]:
        """Ordinary conversation (or a clarifying question), written by the model."""
        reasoner = models.reasoning()
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": conversation_prompt(decision.intent or "conversation",
                                                              profile)},
            *history,
            {"role": "user", "content": question},
        ]
        images = context_builder.resolve_images(list(image_ids))
        try:
            result = await reasoner.generate(
                messages, images=images or None, tools=None,
                context={"purpose": decision.intent, "temperature": 0.6})
        except ModelUnavailable as exc:
            return self._fallback(cid, question, gate, router.RouteDecision(
                available=False, failure=exc.reason), mode, job_id, started_ms, persist)

        text, _ignored_calls = parse_tool_calls(_strip_thinking(result.get("text") or ""))
        text = text.strip() or FALLBACK_TEXT
        # The model's own words still pass the live-work check; hazard notices
        # are not stapled onto chat (only the input gate may add one).
        text = safety.review(text, evidence={}, user_text=question)["text"]
        kind = "clarify" if decision.intent == "ambiguous" else "conversation"
        return self._plain(cid, text, kind, gate, decision, mode, job_id, started_ms, persist)

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
                  job_id, inspection_id, mode, degraded, total_ms, persist, gate=None,
                  decision=None):
        text = _strip_thinking(result.get("text") or "").strip()
        sections = result.get("sections") or _sections_from_text(text)
        meta = result.get("meta") or {}
        verdict = safety.review(text, evidence=evidence, user_text=question, sections=sections)

        # The model decided it didn't have enough to go on and asked one
        # specific question. That goes back as a plain message — no
        # confidence meter or "Observed" scaffolding around a question.
        clarifying = not sections
        if clarifying:
            response = self._plain(conversation["id"], verdict["text"] or text, "clarify", gate,
                                   decision, mode, job_id, ms() - total_ms, persist=False,
                                   record=False)
            response.update({
                "conversational": False, "work_trail": trail,
                "evidence_keys": sorted(evidence), "degraded_tools": sorted(set(degraded)),
                "refs": _refs_from_evidence(evidence), "duration_ms": total_ms,
                "inspection_id": inspection_id, "unverified_figures": verdict["unverified_figures"],
                "safety_notes": verdict["notes"],
            })
            if persist:
                response["message_id"] = M.add_message(
                    conversation["id"], "assistant", response["text"],
                    {"kind": "clarify", "work_trail": trail, "notice": response["notice"],
                     "model": response["model"]})["id"]
            return response

        # Safety order: the input gate first (an active hazard the user
        # reported), then hazards the answer itself touches.
        notice = _public_notice(gate)
        if notice and verdict["hazard_notices"]:
            notice["items"] = notice["items"] + [n for n in verdict["hazard_notices"]
                                                 if n not in notice["items"]]
            notice["note"] = verdict["professional_note"]
        elif verdict["hazard_notices"]:
            notice = {"level": "safety", "title": "Before you touch it",
                      "items": verdict["hazard_notices"],
                      "note": verdict["professional_note"]}
        elif verdict["unverified_figures"]:
            notice = {"level": "need", "title": "Figures to confirm",
                      "items": verdict["unverified_figures"]}

        refs = meta.get("refs") or _refs_from_evidence(evidence)
        confidence = meta.get("confidence")
        if confidence is None:
            confidence = _confidence_from_evidence(evidence)
        remembered = self._remember(question, evidence, job_id, conversation["id"])

        hazards = [h["key"] for h in verdict["hazards"]]
        for k in (gate or {}).get("hazards") or []:
            if k not in hazards:
                hazards.insert(0, k)
        response = {
            "conversation_id": conversation["id"],
            "message_id": None,
            "text": verdict["text"],
            "sections": sections,
            "notice": notice,
            "question": None,
            "refs": refs,
            "evidence_keys": sorted(evidence),
            "work_trail": trail,
            "confidence": confidence,
            "confidence_label": meta.get("confidence_label") or _label(confidence),
            "hazards": hazards,
            "safety_notes": verdict["notes"],
            "unverified_figures": verdict["unverified_figures"],
            "degraded_tools": sorted(set(degraded)),
            "memory": remembered,
            "follow_ups": _follow_ups(evidence, verdict, question),
            "conversational": False,
            "kind": "diagnosis",
            "intent": "technical",
            "route": decision.public() if decision else None,
            "engine_available": True,
            "mode": mode,
            "job_id": job_id,
            "inspection_id": inspection_id,
            "model": self._model_info(),
            "duration_ms": total_ms,
            "created_at": utc_now(),
        }
        if persist:
            stored = M.add_message(
                conversation["id"], "assistant", verdict["text"],
                {k: response[k] for k in
                 ("sections", "notice", "refs", "confidence", "confidence_label",
                  "work_trail", "hazards", "degraded_tools", "model", "kind")})
            response["message_id"] = stored["id"]
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
               "accelerator": reasoner.health().accelerator,
               "npu": reasoner.health().npu and not reasoner.health().hosted,
               "hosted": reasoner.health().hosted}
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


_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def _strip_thinking(text: str) -> str:
    """Reasoning models (Qwen3, DeepSeek-R1…) may emit a <think> block first."""
    return _THINK.sub("", text or "").strip()


def _public_notice(gate: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not gate:
        return None
    # `first`: this came from the safety gate, so it leads the reply — ahead
    # of any conversational text or diagnostic sections.
    return {"level": gate["level"], "title": gate["title"], "items": list(gate["items"]),
            "note": gate.get("note"), "first": True}


def _seed_calls(question: str, history: Sequence[Dict[str, str]], image_ids: Sequence[str],
                doc_count: int, job_id: Optional[str]) -> List[Dict[str, Any]]:
    """SEE and RETRIEVE for a technical turn, before the model reasons.

    This is not routing — the router has already decided the turn is
    technical. It just makes sure the evidence exists even when a small local
    model is poor at calling tools itself.
    """
    calls: List[Dict[str, Any]] = []
    if image_ids:
        newest = image_ids[-1]
        calls.append({"tool": "vision_detect", "arguments": {"image_id": newest}})
        calls.append({"tool": "ocr_extract", "arguments": {"image_id": newest}})
    if doc_count:
        # A short follow-up ("drive end") only makes sense with what came before.
        earlier = [h["content"] for h in history if h.get("role") == "user"][-2:]
        query = " ".join([*earlier, question])[-300:].strip()
        if len(query) >= 2:
            calls.append({"tool": "search_documents", "arguments": {"query": query}})
    if job_id:
        calls.append({"tool": "get_job_history", "arguments": {"job_id": job_id}})
    return calls


orchestrator = Orchestrator()

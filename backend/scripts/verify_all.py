#!/usr/bin/env python3
"""Exercise every feature against a running server and report pass/fail.

    python scripts/verify_all.py [base_url]

This is not the unit suite. It drives the real HTTP surface the front-end uses,
in the order a technician would, and checks the behaviour the specification
asks for rather than just a 200 status. Run it before a demo.
"""

from __future__ import annotations

import io
import json
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8756").rstrip("/")
GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m")

client = httpx.Client(base_url=BASE, timeout=90.0)
results: List[Tuple[str, str, bool, str]] = []
state: Dict[str, Any] = {}


def check(section: str, name: str, fn: Callable[[], Optional[str]]) -> None:
    try:
        detail = fn()
        results.append((section, name, True, detail or ""))
        print(f"  {GREEN}ok{RESET}   {name}" + (f"  {DIM}{detail}{RESET}" if detail else ""))
    except AssertionError as exc:
        results.append((section, name, False, str(exc)))
        print(f"  {RED}FAIL{RESET} {name}\n       {RED}{exc}{RESET}")
    except Exception as exc:
        results.append((section, name, False, f"{type(exc).__name__}: {exc}"))
        print(f"  {RED}ERR {RESET} {name}\n       {RED}{type(exc).__name__}: {exc}{RESET}")


def section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")


# ---------------------------------------------------------------- fixtures

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from tests import fixtures  # noqa: E402


# ============================================================== 1. SYSTEM

section("1. System, status and honesty (§4, §20, §23, §24)")

def _health():
    r = client.get("/api/health").json()
    assert r["status"] == "ok", r
    return f"uptime {r['uptime_s']}s"


def _root():
    r = client.get("/").json()
    assert "VLM is the brain" in r["principle"]
    return r["version"]


def _system_status():
    r = client.get("/api/system/status").json()
    lf = r["local_first"]
    for key in ("cloud_documents", "cloud_camera_frames", "cloud_audio", "cloud_memory"):
        assert lf[key] is False, f"{key} is not local-first"
    assert r["tools"]["count"] >= 19, r["tools"]["count"]
    state["tool_names"] = r["tools"]["names"]
    return f"{r['tools']['count']} tools, vector store {r['storage']['vector_store']['backend']}"


def _models_status():
    r = client.get("/api/models/status").json()
    roles = r["roles"]
    assert set(roles) == {"reasoning", "detector", "classifier", "segmenter", "tracker",
                          "ocr", "embedding", "stt", "tts"}, sorted(roles)
    for role, info in roles.items():
        if info["npu"]:
            assert info["accelerator"] == "npu", f"{role} claims npu without the accelerator"
            assert r["runtime"]["qnn_execution_provider_available"], \
                f"{role} claims npu but this build has no QNN provider"
        if info["synthetic"]:
            assert info["npu"] is False, f"{role} is a stand-in but claims the NPU"
    assert r["summary"]["npu_claim"] == bool(r["summary"]["npu_accelerated"])
    state["models"] = r["summary"]
    return (f"ready={r['summary']['ready']} synthetic={r['summary']['synthetic']} "
            f"npu_claim={r['summary']['npu_claim']}")


def _every_candidate_selectable():
    roles = client.get("/api/models/status").json()["roles"]
    tried = {k: {c["provider"] for c in v["candidates_tried"]} for k, v in roles.items()}
    expect = {
        "reasoning": {"onnxruntime-genai", "local-openai-compat"},
        "detector": {"yolo-onnx", "yolo-world-onnx"},
        "classifier": {"efficientnet-onnx"},
        "segmenter": {"onnx-seg", "sam2-onnx", "mobilesam-onnx"},
        "tracker": {"edgetam-onnx", "track-anything-onnx"},
        "ocr": {"easyocr", "trocr-onnx"},
        "embedding": {"nomic-onnx", "minilm-onnx"},
        "stt": {"whisper-onnx", "faster-whisper"},
        "tts": {"piper"},
    }
    for role, want in expect.items():
        assert want <= tried[role], f"{role} missing candidates: {want - tried[role]}"
    return f"{sum(len(v) for v in tried.values())} candidates across 9 roles"


def _models_reload():
    r = client.post("/api/models/reload").json()
    assert r["reloaded"] is True
    return f"re-probed, npu_claim={r['npu_claim']}"


check("system", "GET /api/health", _health)
check("system", "GET /", _root)
check("system", "GET /api/system/status declares local-first", _system_status)
check("system", "GET /api/models/status is internally consistent", _models_status)
check("system", "every §3 model is selectable by name", _every_candidate_selectable)
check("system", "POST /api/models/reload", _models_reload)


# ============================================================== 2. DOCUMENTS

section("2. Knowledge vault — both representations (§10, §11, §12)")

def _upload_manual():
    r = client.post("/api/documents/upload", files={
        "file": ("CNC-M04 manual.pdf", fixtures.text_only_manual(), "application/pdf")}).json()
    assert r["state"] == "ready", r
    assert r["page_count"] == 4 and r["pages_rendered"] == 4, r
    assert r["index"]["chunks"] > 0, r["index"]
    state["manual"] = r["document_id"]
    return f"{r['page_count']} pages, {r['pages_rendered']} rendered, {r['index']['chunks']} chunks"


def _upload_diagrams():
    r = client.post("/api/documents/upload", files={
        "file": ("Diagrams.pdf", fixtures.diagram_heavy_manual(), "application/pdf")}).json()
    assert r["pages_rendered"] == 3, r
    state["diagrams"] = r["document_id"]
    return f"{r['pages_rendered']} figure pages rendered"


def _upload_schematic():
    r = client.post("/api/documents/upload", files={
        "file": ("Schematic 4412-B.pdf", fixtures.wiring_schematic(), "application/pdf")}).json()
    state["schematic"] = r["document_id"]
    return r["state"]


def _upload_long():
    r = client.post("/api/documents/upload", files={
        "file": ("Service manual.pdf", fixtures.multipage_service_manual(24),
                 "application/pdf")}).json()
    assert r["page_count"] == 24, r
    state["long"] = r["document_id"]
    return f"{r['page_count']} pages, {r['index']['chunks']} chunks"


def _upload_markdown():
    r = client.post("/api/documents/upload", files={
        "file": ("panel notes.md",
                 b"# Panel notes\n\nTerminal X4 feeds the coolant pump contactor KM3.",
                 "text/markdown")}).json()
    assert r["index"]["chunks"] >= 1, r
    return f"{r['mime_type']}, indexed"


def _upload_image_document():
    r = client.post("/api/documents/upload", files={
        "file": ("nameplate.jpg", fixtures.motor_nameplate(), "image/jpeg")}).json()
    assert r["pages_rendered"] == 1, r
    return "image stored as a 1-page visual document"


def _list_documents():
    r = client.get("/api/documents").json()
    assert r["count"] >= 6, r["count"]
    assert all("path" not in d for d in r["documents"]), "internal paths leaked"
    return f"{r['count']} documents, no internal paths exposed"


def _get_document():
    r = client.get(f"/api/documents/{state['manual']}").json()
    assert r["indexed"] is True and len(r["pages"]) == 4, r
    return f"{r['chunk_count']} chunks, {len(r['pages'])} page records"


def _page_image():
    r = client.get(f"/api/documents/{state['manual']}/pages/2")
    assert r.status_code == 200, r.status_code
    assert r.headers["content-type"] == "image/png", r.headers
    assert len(r.content) > 1000
    return f"page 2 PNG, {len(r.content) // 1024} KB"


def _retrieval_cites_right_page():
    """Top-1 must be the right document AND the right page, across the whole vault."""
    cases = {"what does fault code E17 mean": ("CNC-M04 manual.pdf", 2),
             "which bearing is fitted at the drive end": ("CNC-M04 manual.pdf", 3),
             "what is the rated current on the nameplate": ("CNC-M04 manual.pdf", 4),
             "what must I do before removing the terminal cover": ("CNC-M04 manual.pdf", 1),
             "where are the thermistor terminals on the layout": ("Diagrams.pdf", 3),
             "how often do I regrease the drive end bearing": ("Service manual.pdf", 11)}
    for q, (want_doc, want_page) in cases.items():
        hits = client.post("/api/documents/search",
                           json={"query": q, "top_k": 3}).json()["results"]
        assert hits, f"no hit for {q!r}"
        top = hits[0]
        assert top["filename"] == want_doc and top["page_start"] == want_page, (
            f"{q!r} -> {top['filename']} p{top['page_start']}, "
            f"expected {want_doc} p{want_page}")
    return f"{len(cases)}/{len(cases)} queries: right document and right page"


def _retrieval_is_diverse():
    """One document must not monopolise the answer when several are relevant."""
    hits = client.post("/api/documents/search",
                       json={"query": "terminal thermistor motor", "top_k": 5}).json()["results"]
    docs = [h["filename"] for h in hits]
    assert len(set(docs)) >= 2, f"one document took every slot: {docs}"
    assert max(docs.count(d) for d in set(docs)) <= 2, docs
    return f"{len(set(docs))} documents represented in the top {len(hits)}"


def _retrieval_finds_page_17_of_24():
    r = client.post("/api/documents/search",
                    json={"query": "P09 coolant flow switch FS1", "top_k": 3}).json()
    top = r["results"][0]
    assert top["page_start"] == 17, f"cited page {top['page_start']}"
    assert top["filename"] == "Service manual.pdf", top["filename"]
    return f"page 17 of 24, in {r['duration_ms']} ms ({r['strategy']})"


def _exact_token_not_buried():
    hits = client.post("/api/documents/search", json={"query": "E17"}).json()["results"]
    assert "E17" in hits[0]["exact_matches"], hits[0]["exact_matches"]
    return f"exact match wins, score {hits[0]['score']}"


check("documents", "upload a text manual (PDF)", _upload_manual)
check("documents", "upload a diagram-heavy manual", _upload_diagrams)
check("documents", "upload a wiring schematic", _upload_schematic)
check("documents", "upload a 24-page service manual", _upload_long)
check("documents", "upload markdown", _upload_markdown)
check("documents", "upload an image as a document", _upload_image_document)
check("documents", "GET /api/documents", _list_documents)
check("documents", "GET /api/documents/{id}", _get_document)
check("documents", "GET /api/documents/{id}/pages/{n} serves the rendered page", _page_image)
check("documents", "retrieval cites the right document and page", _retrieval_cites_right_page)
check("documents", "no single document monopolises the top-k", _retrieval_is_diverse)
check("documents", "finds one page among 24", _retrieval_finds_page_17_of_24)
check("documents", "an exact technical token is not buried", _exact_token_not_buried)


# ============================================================== 3. JOBS

section("3. Job memory (§13, §14)")

def _create_machine():
    r = client.post("/api/machines", json={
        "name": "CNC Motor #04", "manufacturer": "Siemens",
        "model": "CNC-M04", "serial_number": "SN-99123"}).json()
    state["machine"] = r["id"]
    return r["name"]


def _machine_dedupes():
    again = client.post("/api/machines", json={"serial_number": "SN-99123",
                                               "manufacturer": "Siemens AG"}).json()
    assert again["id"] == state["machine"], "the same serial created a second machine"
    assert again["manufacturer"] == "Siemens AG", again
    return "matched on serial and merged"


def _create_job():
    r = client.post("/api/jobs", json={"title": "Overheating and vibration",
                                       "machine_id": state["machine"]}).json()
    state["job"] = r["id"]
    return r["title"]


def _start_inspection():
    r = client.post("/api/inspections", json={"job_id": state["job"], "mode": "photo"}).json()
    state["inspection"] = r["id"]
    return f"mode={r['mode']}"


def _record_measurement():
    r = client.post("/api/measurements", json={
        "inspection_id": state["inspection"], "name": "temperature",
        "value": 87.0, "unit": "C"}).json()
    return f"{r['name']} {r['value']} {r['unit']}"


def _refuse_valueless_measurement():
    r = client.post("/api/measurements", json={
        "inspection_id": state["inspection"], "name": "current", "unit": "A"})
    assert r.status_code == 422, r.status_code
    return "422 — a measurement without a value is refused"


def _record_finding():
    r = client.post("/api/findings", json={
        "inspection_id": state["inspection"],
        "description": "Drive-end bearing shows heat discolouration and play",
        "type": "fault", "confidence": 0.78}).json()
    return f"confidence {r['confidence']}"


def _memory_refuses_speculation():
    r = client.post("/api/memories", json={
        "memory_type": "fault", "content": "It might be the bearing, not sure",
        "confidence": 0.9, "job_id": state["job"], "source": {"origin": "verify"}}).json()
    assert r["stored"] is False, r
    assert "speculative" in r["reason"], r["reason"]
    return r["reason"][:52] + "…"


def _memory_refuses_chatter():
    r = client.post("/api/memories", json={
        "memory_type": "preference", "content": "thanks", "confidence": 0.9,
        "confirmed": True, "source": {"origin": "verify"}}).json()
    assert r["stored"] is False, r
    return r["reason"]


def _memory_refuses_missing_confidence():
    r = client.post("/api/memories", json={
        "memory_type": "fault", "content": "Winding insulation has degraded",
        "confirmed": True, "source": {"origin": "verify"}}).json()
    assert r["stored"] is False, r
    return r["reason"]


def _memory_accepts_confirmed():
    r = client.post("/api/memories", json={
        "memory_type": "repair_action",
        "content": "Confirmed drive-end bearing wear; replaced with NSK 6203-2RS "
                   "and re-torqued the end shield to 24 Nm",
        "confidence": 0.93, "confirmed": True, "job_id": state["job"],
        "source": {"origin": "technician"}}).json()
    assert r["stored"] is True, r
    state["memory"] = r["memory"]["id"]
    return "stored with confidence and source"


def _job_history():
    r = client.get(f"/api/jobs/{state['job']}").json()
    assert r["machine"]["serial_number"] == "SN-99123"
    assert len(r["findings"]) == 1 and len(r["measurements"]) == 1
    assert len(r["memories"]) == 1
    return (f"{len(r['inspections'])} inspection, {len(r['findings'])} finding, "
            f"{len(r['measurements'])} measurement, {len(r['memories'])} memory")


def _user_and_preferences():
    u = client.get("/api/user").json()
    assert u["id"], u
    client.patch("/api/user", params={"display_name": "Simon"})
    pref = {"memory_type": "preference",
            "content": "Prefers torque figures in Nm rather than lb-ft",
            "confidence": 0.9, "confirmed": True, "source": {"origin": "technician"}}
    first = client.post("/api/memories", json=pref).json()
    again = client.post("/api/memories", json=pref).json()
    # §13: the same fact twice is noise, so the second write is refused.
    assert again["stored"] is False, again
    assert "identical" in again["reason"], again["reason"]
    u2 = client.get("/api/user").json()
    assert u2["display_name"] == "Simon" and u2["preference_count"] >= 1, u2
    return (f"{u2['display_name']}, {u2['preference_count']} preference; "
            "an identical repeat is refused")


check("jobs", "POST /api/machines", _create_machine)
check("jobs", "the same serial does not create a duplicate machine", _machine_dedupes)
check("jobs", "POST /api/jobs", _create_job)
check("jobs", "POST /api/inspections", _start_inspection)
check("jobs", "POST /api/measurements", _record_measurement)
check("jobs", "a measurement with no value is refused (§18)", _refuse_valueless_measurement)
check("jobs", "POST /api/findings", _record_finding)
check("jobs", "write policy refuses speculation (§13)", _memory_refuses_speculation)
check("jobs", "write policy refuses chatter", _memory_refuses_chatter)
check("jobs", "write policy refuses a memory with no confidence", _memory_refuses_missing_confidence)
check("jobs", "write policy accepts a confirmed repair", _memory_accepts_confirmed)
check("jobs", "GET /api/jobs/{id} returns full history", _job_history)
check("jobs", "GET/PATCH /api/user with durable preferences", _user_and_preferences)


# ============================================================== 4. AGENT

section("4. The agent loop (§2, §15, §16, §18, §19)")

def _chat_quotes_and_cites():
    r = client.post("/api/chat", json={
        "message": "Fault code E17 is showing and I measured 87 C at the housing. "
                   "What does it mean and where should I test?",
        "job_id": state["job"]}).json()
    state["conversation"] = r["conversation_id"]
    tools = [s["tool"] for s in r["work_trail"]]
    assert "search_documents" in tools, tools
    assert "thermal overload" in r["text"].lower(), "the manual's wording was not carried through"
    assert "87" in r["text"], "the technician's own measurement was dropped"
    docs = [x for x in r["refs"] if x["kind"] in ("document", "document_page")]
    assert docs and docs[0]["page"] == 2, docs
    assert r["duration_ms"] > 0, "duration_ms is not being measured"
    state["chat"] = r
    return f"{len(tools)} tools, cited p{docs[0]['page']}, {r['duration_ms']:.0f} ms"


def _chat_has_the_spec_sections():
    kinds = [s["kind"] for s in state["chat"]["sections"]]
    for want in ("observed", "inferred", "next"):
        assert want in kinds, f"missing §18 section: {want} (got {kinds})"
    return " / ".join(dict.fromkeys(kinds))


def _hazard_notice():
    r = state["chat"]
    assert r["hazards"], "a hot electrical machine produced no hazard"
    assert r["notice"]["level"] == "safety", r["notice"]
    assert r["notice"]["note"], "no professional-procedure caveat"
    return ", ".join(r["hazards"])


def _confidence_reported():
    r = state["chat"]
    assert 0.0 < r["confidence"] < 1.0, r["confidence"]
    assert r["confidence_label"], r
    assert r["model"]["provider"], r["model"]
    return f"{r['confidence']} {r['confidence_label']} via {r['model']['provider']}"


def _degraded_tools_named():
    r = client.post("/api/photo/analyze",
                    files={"file": ("m.jpg", fixtures.motor_assembly(), "image/jpeg")},
                    data={"question": "What is this and what should I check?"}).json()
    assert "vision_detect" in r["degraded_tools"], r["degraded_tools"]
    observed = " ".join(i for s in r["sections"] if s["kind"] == "observed"
                        for i in s["items"]).lower()
    assert "no detector or ocr result is available" in observed, observed[:200]
    return "says it cannot confirm the image visually"


def _second_visit_recalls():
    r = client.post("/api/chat", json={
        "message": "I'm back at CNC Motor #04. What did we find last time?",
        "job_id": state["job"]}).json()
    assert "get_job_history" in {s["tool"] for s in r["work_trail"]}
    assert "bearing" in r["text"].lower(), r["text"][:200]
    return "prior finding surfaced on the second visit"


def _diagram_question_opens_the_page():
    r = client.post("/api/chat", json={
        "message": "Where are the thermistor terminals on the terminal layout diagram?"}).json()
    assert "get_document_page" in {s["tool"] for s in r["work_trail"]}, \
        [s["tool"] for s in r["work_trail"]]
    pages = [x for x in r["refs"] if x["kind"] == "document_page"]
    assert pages, r["refs"]
    return f"opened {pages[0]['filename']} page {pages[0]['page']} as an image"


def _uncertainty_is_stated():
    r = client.post("/api/chat", json={
        "message": "The flange on the zorp unit is behaving oddly."}).json()
    items = " ".join(i for s in r["sections"] for i in s["items"]).lower()
    assert "unknown" in items, items[:200]
    assert r["confidence"] < 0.5, r["confidence"]
    return f"Unknown, confidence {r['confidence']} ({r['confidence_label']})"


def _no_invented_measurement():
    r = client.post("/api/chat", json={
        "message": "The motor is running hot. What temperature is it at?"}).json()
    assert not r["unverified_figures"], r["unverified_figures"]
    needs = [s for s in r["sections"] if s["kind"] == "measure"]
    assert needs, "it did not ask for the missing reading"
    return "asked for the reading instead of inventing one"


def _web_is_last_resort():
    r = client.post("/api/chat", json={
        "message": "What does fault code E17 mean?", "web": True}).json()
    trail = [s["tool"] for s in r["work_trail"]]
    assert "web_search" not in trail, f"web ran despite a local answer: {trail}"
    return "local manual answered it; the web was not consulted"


def _streaming_order():
    events = []
    with client.stream("POST", "/api/chat/stream",
                       json={"message": "The pump is leaking oil at the rod end."}) as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if line.startswith("data: ") and "[DONE]" not in line:
                events.append(json.loads(line[6:]))
    kinds = [e["type"] for e in events]
    assert kinds[0] == "start" and kinds[-1] == "done", kinds[:3]
    assert "model" in kinds
    assert kinds.index("step") < kinds.index("text"), "text arrived before the work trail"
    assert events[-1]["result"]["text"]
    return f"{len(events)} events: start → model → step… → text… → done"


def _conversation_persists():
    r = client.get(f"/api/conversations/{state['conversation']}").json()
    roles = [m["role"] for m in r["messages"]]
    assert roles.count("user") >= 1 and roles.count("assistant") >= 1, roles
    listing = client.get("/api/conversations").json()
    assert any(c["id"] == state["conversation"] for c in listing["conversations"])
    return f"{len(r['messages'])} messages, {listing['count']} conversations"


check("agent", "POST /api/chat quotes and cites the manual", _chat_quotes_and_cites)
check("agent", "the answer has the §18 sections", _chat_has_the_spec_sections)
check("agent", "hazard notice attached (§19)", _hazard_notice)
check("agent", "confidence and model provenance reported", _confidence_reported)
check("agent", "a missing sense is named, not papered over (§25)", _degraded_tools_named)
check("agent", "the second visit recalls the first (§13)", _second_visit_recalls)
check("agent", "a spatial question opens the page image (§11)", _diagram_question_opens_the_page)
check("agent", "uncertainty is stated as Unknown (§18)", _uncertainty_is_stated)
check("agent", "no measurement is invented (§18)", _no_invented_measurement)
check("agent", "web research is a last resort (§16)", _web_is_last_resort)
check("agent", "POST /api/chat/stream sends the trail before the text", _streaming_order)
check("agent", "conversations persist and list", _conversation_persists)


# ======================================================== 4b. CONVERSATION

section("4b. Ordinary conversation (§1)")

def _greeting_is_a_greeting():
    r = client.post("/api/chat", json={"message": "hi"}).json()
    assert r["conversational"] is True, r.get("text", "")[:120]
    assert r["work_trail"] == [], "a greeting ran tools"
    assert r["sections"] == [] and r["notice"] is None and r["confidence"] is None, \
        "a greeting came back with diagnostic furniture"
    assert r["text"].lower().startswith("hello"), r["text"][:80]
    assert r["follow_ups"] == [], "a greeting came back with suggestion chips"
    return f"{r['duration_ms']:.1f} ms, 0 tools, no chips"


def _capability_answer_is_grounded():
    r = client.post("/api/chat", json={"message": "what can you do?"}).json()
    assert r["conversational"] is True and r["intent"] == "capability"
    assert "cite the page" in r["text"], r["text"][:160]
    assert "invent a measurement" in r["text"], "it did not state its limits"
    return "describes real capabilities and its limits"


def _identity_answer_is_honest():
    r = client.post("/api/chat", json={"message": "are you chatgpt?"}).json()
    text = r["text"].lower()
    assert "visionfield" in text
    if r["model"]["synthetic"]:
        assert "stand-in" in text and "not a language model" in text, r["text"]
    return "names the actual engine"


def _chat_does_not_swallow_work():
    for message in ("hi, fault code E17 is showing",
                    "thanks, but the bearing is still grinding",
                    "hello, can you read this nameplate"):
        r = client.post("/api/chat", json={"message": message}).json()
        assert r.get("conversational") is not True, f"{message!r} was treated as chat"
        assert r["work_trail"], f"{message!r} ran no tools"
    return "3 chatty-looking questions still reached the agent loop"


check("chat", "a greeting gets a greeting, not a form", _greeting_is_a_greeting)
check("chat", "\"what can you do\" is answered from what is there", _capability_answer_is_grounded)
check("chat", "\"are you chatgpt\" gets the truth", _identity_answer_is_honest)
check("chat", "work is never mistaken for chat", _chat_does_not_swallow_work)


# ============================================================== 5. PHOTO

section("5. Photo mode (§7)")

def _photo_upload_then_inspect():
    up = client.post("/api/photo/upload", files={
        "file": ("pcb.jpg", fixtures.pcb_with_labels(), "image/jpeg")}).json()
    state["image"] = up["image_id"]
    r = client.post("/api/photo/inspect", data={"image_id": up["image_id"]}).json()
    assert r["detect"]["ok"] and r["detect"]["degraded"], r["detect"]
    assert r["detect"]["fallback"], "no fallback named"
    assert r["detect"]["image"]["width"] == 800, r["detect"]["image"]
    return f"{up['width']}x{up['height']} stored; senses report degraded with a fallback"


def _photo_analyze_multiple():
    r = client.post("/api/photo/analyze-multiple", files=[
        ("files", ("a.jpg", fixtures.motor_nameplate(), "image/jpeg")),
        ("files", ("b.jpg", fixtures.damaged_component(), "image/jpeg")),
    ], data={"question": "Same machine, two angles. What can you tell me?"}).json()
    assert len(r["image_ids"]) == 2, r["image_ids"]
    return f"{len(r['image_ids'])} photos in one inspection context"


def _poor_frames_described():
    blur = client.post("/api/photo/analyze",
                       files={"file": ("b.jpg", fixtures.blurred_frame(), "image/jpeg")},
                       data={"question": "What is this?"}).json()
    obs = " ".join(i for s in blur["sections"] if s["kind"] == "observed"
                   for i in s["items"]).lower()
    assert "low in edge detail" in obs, obs[:160]

    dark = client.post("/api/photo/analyze",
                       files={"file": ("d.jpg", fixtures.dark_frame(), "image/jpeg")},
                       data={"question": "Read this label"}).json()
    obs2 = " ".join(i for s in dark["sections"] if s["kind"] == "observed"
                    for i in s["items"]).lower()
    assert "underexposed" in obs2, obs2[:160]
    return "blur and underexposure both reported"


def _classification_stage_is_optional():
    r = client.post("/api/tools/call", json={
        "tool": "vision_classify", "arguments": {"image_id": state["image"]}}).json()
    assert r["ok"] is True, r
    assert r["skipped"] is True and r["degraded"] is True, r
    assert r["fallback"], r
    return "skipped cleanly with a named fallback, no guessed class"


def _non_image_refused():
    r = client.post("/api/photo/upload", files={
        "file": ("fake.jpg", b"this is plain text, not a JPEG", "image/jpeg")})
    assert r.status_code == 415, r.status_code
    return "415 — content is checked, not the extension"


check("photo", "POST /api/photo/upload then /inspect", _photo_upload_then_inspect)
check("photo", "POST /api/photo/analyze-multiple", _photo_analyze_multiple)
check("photo", "poor frames are described honestly", _poor_frames_described)
check("photo", "classification is an optional stage (§7)", _classification_stage_is_optional)
check("photo", "a non-image upload is refused", _non_image_refused)


# ============================================================== 6. LIVE

section("6. Live mode — the VLM must not run per frame (§8)")

def _live_start():
    r = client.post("/api/live/start", json={"job_id": state["job"]}).json()
    state["live"] = r["session_id"]
    state["live_policy"] = r["policy"]
    assert r["policy"]["vlm_min_gap_ms"] > 0, r["policy"]
    return (f"detect {r['policy']['detect_interval_ms']}ms, ocr "
            f"{r['policy']['ocr_interval_ms']}ms, vlm gap {r['policy']['vlm_min_gap_ms']}ms")


def _live_rate_limiting():
    frame = fixtures.motor_assembly()
    ran = []
    for _ in range(6):
        r = client.post("/api/live/frame", files={"file": ("f.jpg", frame, "image/jpeg")},
                        data={"session_id": state["live"]}).json()
        ran.append(r["ran"]["reasoning"])
    assert ran[0] is True, "the first frame of a new scene did not wake the model"
    assert not any(ran[1:]), f"the model woke on an unchanged scene: {ran}"
    return f"6 identical frames → {sum(ran)} reasoning call"


def _live_scene_change():
    """Panning to a different subject must wake the senses immediately."""
    threshold = state["live_policy"]["scene_change_threshold"]
    r = client.post("/api/live/frame",
                    files={"file": ("f.jpg", fixtures.control_panel(), "image/jpeg")},
                    data={"session_id": state["live"]}).json()
    assert r["scene_change"] >= threshold, (
        f"panning from a motor to a control panel scored only {r['scene_change']} "
        f"against a threshold of {threshold} — the senses would not wake")
    assert r["ran"]["detector"] and r["ran"]["ocr"], r["ran"]
    return f"scene change {r['scene_change']:.2f} ≥ {threshold} woke the detector and OCR"


def _live_ignores_camera_shake():
    """Exposure drift and a small hand movement must NOT count as a new scene."""
    import io as _io

    from PIL import Image, ImageEnhance

    base = fixtures.control_panel()
    img = Image.open(_io.BytesIO(base))
    shifted = img.transform(img.size, Image.AFFINE, (1, 0, 5, 0, 1, 4))
    brighter = ImageEnhance.Brightness(img).enhance(1.3)

    threshold = state["live_policy"]["scene_change_threshold"]
    worst = 0.0
    for name, variant in (("shift", shifted), ("exposure", brighter)):
        buf = _io.BytesIO()
        variant.convert("RGB").save(buf, format="JPEG", quality=92)
        r = client.post("/api/live/frame",
                        files={"file": ("f.jpg", buf.getvalue(), "image/jpeg")},
                        data={"session_id": state["live"]}).json()
        worst = max(worst, r["scene_change"])
        assert r["scene_change"] < threshold, (
            f"a camera {name} scored {r['scene_change']} and would have been "
            f"treated as a new scene")
    return f"shake and exposure drift peaked at {worst:.3f}, under {threshold}"


def _live_question_always_wakes():
    r = client.post("/api/live/frame",
                    files={"file": ("f.jpg", fixtures.control_panel(), "image/jpeg")},
                    data={"session_id": state["live"], "question": "What am I looking at?"}).json()
    assert r["ran"]["reasoning"] is True, r["vlm"]
    assert "the technician asked a question" in r["vlm"]["reasons"], r["vlm"]["reasons"]
    return "a direct question overrides the rate limit"


def _live_reasons_are_explicit():
    r = client.post("/api/live/frame",
                    files={"file": ("f.jpg", fixtures.control_panel(), "image/jpeg")},
                    data={"session_id": state["live"]}).json()
    assert "should_call_vlm" in r["vlm"] and "reasons" in r["vlm"], r["vlm"]
    assert "timings_ms" in r, r.keys()
    return f"decision returned per frame: {r['vlm']['should_call_vlm']}"


def _live_unknown_session():
    r = client.post("/api/live/frame",
                    files={"file": ("f.jpg", fixtures.dark_frame(), "image/jpeg")},
                    data={"session_id": "live_doesnotexist"})
    assert r.status_code == 404, r.status_code
    return "404 for an unknown session"


def _live_sessions_listed():
    r = client.get("/api/live/sessions").json()
    assert r["count"] >= 1, r
    mine = next((x for x in r["sessions"] if x["session_id"] == state["live"]), None)
    assert mine is not None, f"this session is not listed: {[x['session_id'] for x in r['sessions']]}"
    for key in ("camera_fps", "tracking_fps", "detector_fps", "vlm_calls_per_minute"):
        assert key in mine, f"missing §23 figure: {key}"
    assert mine["frames_seen"] > 0 and mine["camera_fps"] > 0, mine
    return (f"camera {mine['camera_fps']} fps, detector {mine['detector_fps']} fps, "
            f"{mine['vlm_calls']} vlm calls over {mine['frames_seen']} frames")


def _live_stop():
    r = client.post("/api/live/stop", data={"session_id": state["live"]}).json()
    assert r["status"] == "stopped", r
    assert r["frames_seen"] >= 9, r["frames_seen"]
    assert r["vlm_calls"] <= 4, f"{r['vlm_calls']} VLM calls for {r['frames_seen']} frames"
    return (f"{r['frames_seen']} frames → {r['vlm_calls']} VLM calls "
            f"({r['frames_per_vlm_call']} frames per call)")


check("live", "POST /api/live/start returns its policy", _live_start)
check("live", "an unchanged scene does not wake the model", _live_rate_limiting)
check("live", "a scene change wakes the detector and OCR", _live_scene_change)
check("live", "camera shake and exposure drift do not", _live_ignores_camera_shake)
check("live", "a question always wakes the model", _live_question_always_wakes)
check("live", "the decision and its reasons are returned per frame", _live_reasons_are_explicit)
check("live", "an unknown session is rejected", _live_unknown_session)
check("live", "GET /api/live/sessions reports FPS (§23)", _live_sessions_listed)
check("live", "POST /api/live/stop", _live_stop)


# ============================================================== 7. VOICE

section("7. Voice (§17, §25)")

def _transcribe_degrades():
    r = client.post("/api/voice/transcribe", files={
        "file": ("clip.wav", b"RIFF\x00\x00\x00\x00WAVEfmt ", "audio/wav")}).json()
    assert r["degraded"] is True and r["text"] == "", r
    assert "fallback" in r, r
    return r["fallback"][:56] + "…"


def _synthesize_degrades():
    r = client.post("/api/voice/synthesize",
                    json={"text": "Isolate the supply before testing."}).json()
    assert r["degraded"] is True, r
    assert r["text"] == "Isolate the supply before testing.", r
    return "text response still stands"


check("voice", "POST /api/voice/transcribe degrades locally", _transcribe_degrades)
check("voice", "POST /api/voice/synthesize degrades locally", _synthesize_degrades)


# ============================================================== 8. REPORTS

section("8. Reports (§15)")

def _create_report():
    client.post("/api/measurements", json={
        "inspection_id": state["inspection"], "name": "temperature",
        "value": 61.0, "unit": "C"})
    r = client.post("/api/reports", json={
        "job_id": state["job"],
        "summary": "Bearing wear caused the thermal trip. Replaced; temperature settled at 61 C.",
        "recommendations": ["Re-check vibration after 100 running hours"]}).json()
    md = r["markdown"]
    for token in ("CNC Motor #04", "SN-99123", "87.0", "61.0", "NSK 6203-2RS",
                  "not a substitute for the manufacturer"):
        assert token in md, f"report is missing {token!r}"
    state["report"] = r["report_id"]
    return f"{r['findings']} finding, {r['measurements']} measurements, {len(md)} chars"


def _empty_report_invents_nothing():
    job = client.post("/api/jobs", json={"title": "Nothing recorded"}).json()
    md = client.post("/api/reports", json={"job_id": job["id"]}).json()["markdown"]
    assert "None recorded." in md, md[:300]
    assert "no values have been estimated" in md.lower()
    return "empty sections say they are empty"


def _list_and_fetch_report():
    listing = client.get("/api/reports", params={"job_id": state["job"]}).json()
    assert listing["count"] == 1, listing
    one = client.get(f"/api/reports/{state['report']}").json()
    assert one["markdown"].startswith("# Service report"), one["markdown"][:60]
    return f"{listing['count']} report for this job"


check("reports", "POST /api/reports builds from recorded evidence", _create_report)
check("reports", "a report on an empty job invents nothing", _empty_report_invents_nothing)
check("reports", "GET /api/reports and /{id}", _list_and_fetch_report)


# ============================================================== 9. SECURITY

section("9. Security posture (§15, §24)")

def _tool_allowlist():
    r = client.post("/api/tools/call", json={
        "tool": "run_shell", "arguments": {"cmd": "rm -rf /"}}).json()
    assert r["ok"] is False and r["error"] == "TOOL_NOT_ALLOWED", r
    return "an unregistered tool never reaches a handler"


def _no_dangerous_tools():
    names = {t["name"] for t in client.get("/api/tools").json()["tools"]}
    forbidden = {"shell", "bash", "exec", "run_command", "read_file", "write_file",
                 "python", "eval", "sql"}
    assert not (forbidden & names), forbidden & names
    return f"{len(names)} tools, none of them a shell or filesystem tool"


def _ssrf_refused():
    for url in ("http://127.0.0.1:8756/api/system/status", "http://192.168.1.1/admin",
                "http://169.254.169.254/latest/meta-data/", "file:///etc/passwd"):
        r = client.post("/api/tools/call", json={
            "tool": "fetch_web_source", "arguments": {"url": url}}).json()
        assert r["fetched"] is False, f"{url} was fetched"
    return "loopback, private, link-local and file:// all refused"


def _web_off_by_default():
    r = client.post("/api/tools/call", json={
        "tool": "web_search", "arguments": {"query": "Siemens E17"}}).json()
    assert r["degraded"] is True and r["results"] == [], r
    return "web research is off unless configured"


def _path_traversal():
    r = client.get("/api/documents/..%2f..%2fetc/pages/1")
    assert r.status_code == 404, r.status_code
    bad = client.get(f"/api/documents/{state['manual']}/pages/9999")
    assert bad.status_code == 404, bad.status_code
    return "traversal and out-of-range pages both 404"


def _renamed_executable_refused():
    r = client.post("/api/documents/upload", files={
        "file": ("payload.pdf", b"MZ\x90\x00" + b"\x00" * 300, "application/pdf")})
    assert r.status_code == 415, r.status_code
    assert r.json()["error"] == "UNSUPPORTED_MEDIA"
    return "an executable renamed .pdf is refused on its bytes"


def _tool_argument_validation():
    r = client.post("/api/tools/call", json={
        "tool": "search_documents", "arguments": {"query": "x", "top_k": 999}}).json()
    assert r["ok"] is False and r["error"] == "VALIDATION_FAILED", r
    return "arguments are validated before the handler runs"


def _errors_do_not_leak():
    r = client.get("/api/documents/doc_nonexistent")
    body = r.json()
    assert r.status_code == 404 and body["error"] == "NOT_FOUND", body
    assert "Traceback" not in json.dumps(body)
    return "structured envelope, no stack trace"


check("security", "the tool registry is the allowlist", _tool_allowlist)
check("security", "no shell, filesystem or eval tool exists", _no_dangerous_tools)
check("security", "fetch_web_source refuses local and private addresses", _ssrf_refused)
check("security", "web search is off by default (§24)", _web_off_by_default)
check("security", "path traversal is contained", _path_traversal)
check("security", "uploads are identified by content", _renamed_executable_refused)
check("security", "tool arguments are schema-validated", _tool_argument_validation)
check("security", "errors leave as the §25 envelope", _errors_do_not_leak)


# ============================================================== 10. METRICS

section("10. Metrics (§23)")

def _metrics_measured():
    m = client.get("/api/metrics").json()
    lat = m["latency"]
    assert lat["end_to_end_response_latency"]["samples"] > 0, lat
    assert lat["end_to_end_response_latency"]["mean"] > 0, "end-to-end latency is zero"
    assert lat["first_token_latency"]["samples"] > 0, lat
    assert m["tool_latency"], m
    state["metrics"] = m
    e2e = lat["end_to_end_response_latency"]
    return (f"e2e median {e2e['median']} ms (p95 {e2e['p95']}), "
            f"first token {lat['first_token_latency']['median']} ms")


def _metrics_host():
    h = state["metrics"]["host"]
    assert "process_rss_mb" in h or "note" in h, h
    return f"rss {h.get('process_rss_mb')} MB, cpu {h.get('process_cpu_percent')}%"


def _metrics_tools():
    rows = state["metrics"]["tool_latency"]
    by = {r["tool"]: r for r in rows}
    assert "search_documents" in by, sorted(by)
    return ", ".join(f"{r['tool']} {r['avg_ms']:.1f}ms×{r['calls']}" for r in rows[:3])


def _metrics_declare_the_unmeasurable():
    m = state["metrics"]
    assert set(m["unavailable_metrics"]) == {
        "npu_utilisation", "gpu_utilisation", "tokens_per_second"}, m["unavailable_metrics"]
    for role, info in m["accelerators"].items():
        if info["synthetic"]:
            assert info["npu"] is False, f"{role} is a stand-in but claims the NPU"
    return "3 figures named as unavailable rather than invented"


check("metrics", "latency is measured, not zero", _metrics_measured)
check("metrics", "host CPU and memory", _metrics_host)
check("metrics", "per-tool latency", _metrics_tools)
check("metrics", "what cannot be measured is named (§4)", _metrics_declare_the_unmeasurable)


# ============================================================== 11. CLEANUP

section("11. Deletion and cleanup")

def _delete_document():
    before = client.post("/api/documents/search", json={"query": "E17"}).json()["count"]
    assert before > 0
    r = client.delete(f"/api/documents/{state['manual']}").json()
    assert r["deleted"] is True and r["chunks_removed"] > 0, r
    hits = client.post("/api/documents/search", json={"query": "E17"}).json()["results"]
    assert not any(h["document_id"] == state["manual"] for h in hits), \
        "deleted document still appears in search"
    return f"{r['chunks_removed']} chunks and their vectors removed"


def _forget_memory():
    r = client.delete(f"/api/memories/{state['memory']}").json()
    assert r["deleted"] is True, r
    remaining = client.get("/api/memories", params={"job_id": state["job"]}).json()
    assert not any(m["id"] == state["memory"] for m in remaining["memories"])
    return "memory and its vector removed"


def _delete_conversation():
    r = client.delete(f"/api/conversations/{state['conversation']}").json()
    assert r["deleted"] is True
    assert client.get(f"/api/conversations/{state['conversation']}").status_code == 404
    return "conversation and its messages removed"


check("cleanup", "DELETE /api/documents/{id} removes chunks and vectors", _delete_document)
check("cleanup", "DELETE /api/memories/{id}", _forget_memory)
check("cleanup", "DELETE /api/conversations/{id}", _delete_conversation)


# ================================================================ SUMMARY

passed = sum(1 for *_, ok, _ in results if ok)
failed = len(results) - passed
print(f"\n{BOLD}{'=' * 74}{RESET}")
by_section: Dict[str, List[bool]] = {}
for sect, _, ok, _d in results:
    by_section.setdefault(sect, []).append(ok)
for sect, oks in by_section.items():
    bad = len(oks) - sum(oks)
    mark = f"{GREEN}✓{RESET}" if not bad else f"{RED}✗{RESET}"
    print(f"  {mark} {sect:<10} {sum(oks)}/{len(oks)}")
print(f"{BOLD}{'=' * 74}{RESET}")
if failed:
    print(f"{RED}{BOLD}{failed} of {len(results)} checks FAILED{RESET}\n")
    for sect, name, ok, detail in results:
        if not ok:
            print(f"  {RED}✗ [{sect}] {name}{RESET}\n      {detail}")
else:
    print(f"{GREEN}{BOLD}all {passed} checks passed{RESET}")
print()
client.close()
sys.exit(1 if failed else 0)

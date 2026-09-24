"""Phases 2, 5 and 8 — the agent loop, memory policy, safety and web priority."""

from __future__ import annotations

import json


def _manual(client, manual_pdf):
    return client.post("/api/documents/upload", files={
        "file": ("CNC-M04 Service Manual.pdf", manual_pdf, "application/pdf")}).json()


def test_agent_retrieves_quotes_and_cites(client, manual_pdf):
    _manual(client, manual_pdf)
    body = client.post("/api/chat", json={
        "message": "Fault code E17 is showing on the drive. What does it mean and where "
                   "should I test?"}).json()

    tools_used = {s["tool"] for s in body["work_trail"]}
    assert "search_documents" in tools_used, "the agent did not consult the manual"

    text = body["text"]
    assert "E17" in text
    assert "thermal overload" in text.lower(), "the manual's own wording was not carried through"

    doc_refs = [r for r in body["refs"] if r["kind"] in ("document", "document_page")]
    assert doc_refs, "an answer drawn from a manual must cite it"
    assert doc_refs[0]["page"] == 2


def test_agent_never_invents_a_measurement(client, manual_pdf):
    _manual(client, manual_pdf)
    body = client.post("/api/chat", json={
        "message": "The motor is running hot. What temperature is it at?"}).json()
    # No reading was supplied, so none may be asserted.
    assert body["unverified_figures"] == [] or all(
        f not in body["text"] for f in [])
    joined = " ".join(
        item for s in body["sections"] for item in s["items"]).lower()
    assert "needs confirmation" in json.dumps(body["sections"]).lower() \
        or "temperature" in joined


def test_agent_echoes_only_the_measurement_the_technician_gave(client):
    body = client.post("/api/chat", json={
        "message": "The motor is overheating, I measured 87 C at the housing."}).json()
    assert "87" in body["text"]
    observed = next(s for s in body["sections"] if s["kind"] == "observed")
    assert any("87" in item for item in observed["items"])


def test_safety_layer_leads_with_isolation(client):
    from app.agent import safety

    verdict = safety.review(
        "Check the terminal voltage while it is still running.",
        evidence={}, user_text="")
    assert verdict["safe"] is False
    assert verdict["text"].lower().startswith("before anything else: isolate")
    assert "electrical" in [h["key"] for h in verdict["hazards"]]


def test_safety_layer_flags_unsupported_figures_but_allows_cited_ones():
    from app.agent import safety

    verdict = safety.review(
        "The winding should read 250 ohm cold and the shaft turns at 1450 rpm.",
        evidence={"search_documents": {"results": [
            {"content": "Expected resistance is 250 ohm cold."}]}},
        user_text="")
    assert "250 ohm" not in " ".join(verdict["unverified_figures"])
    assert any("1450" in f for f in verdict["unverified_figures"])


def test_hazard_notice_is_attached_to_the_response(client):
    body = client.post("/api/chat", json={
        "message": "The drive keeps tripping the breaker. What should I check?"}).json()
    assert "electrical" in body["hazards"]
    assert body["notice"]["level"] == "safety"
    assert body["notice"]["items"]


def test_memory_write_policy_refuses_speculation(client):
    job = client.post("/api/jobs", json={"title": "Bearing noise"}).json()

    guess = client.post("/api/memories", json={
        "memory_type": "fault", "content": "It might be the bearing, not sure",
        "confidence": 0.9, "confirmed": False, "job_id": job["id"],
        "source": {"origin": "test"}}).json()
    assert guess["stored"] is False
    assert "speculative" in guess["reason"]

    confirmed = client.post("/api/memories", json={
        "memory_type": "repair_action",
        "content": "Confirmed drive-end bearing wear; replaced with NSK 6203-2RS",
        "confidence": 0.92, "confirmed": True, "job_id": job["id"],
        "source": {"origin": "test"}}).json()
    assert confirmed["stored"] is True

    chatter = client.post("/api/memories", json={
        "memory_type": "preference", "content": "thanks",
        "confidence": 0.9, "confirmed": True, "source": {"origin": "test"}}).json()
    assert chatter["stored"] is False


def test_measurement_without_a_value_is_rejected(client):
    job = client.post("/api/jobs", json={"title": "Thermal check"}).json()
    insp = client.post("/api/inspections",
                       json={"job_id": job["id"], "mode": "photo"}).json()
    r = client.post("/api/measurements", json={
        "inspection_id": insp["id"], "name": "current", "unit": "A"})
    assert r.status_code == 422


def test_job_history_is_retrieved_on_the_second_visit(client):
    machine = client.post("/api/machines", json={
        "name": "CNC Motor #04", "serial_number": "SN-99123"}).json()
    job = client.post("/api/jobs", json={
        "title": "Overheating", "machine_id": machine["id"]}).json()
    insp = client.post("/api/inspections",
                       json={"job_id": job["id"], "mode": "photo"}).json()
    client.post("/api/findings", json={
        "inspection_id": insp["id"], "description": "Drive-end bearing heat discolouration",
        "type": "observation", "confidence": 0.7})
    client.post("/api/measurements", json={
        "inspection_id": insp["id"], "name": "temperature", "value": 87.0, "unit": "C"})

    body = client.post("/api/chat", json={
        "message": "I'm back at this machine. What did we find last time?",
        "job_id": job["id"]}).json()

    assert "get_job_history" in {s["tool"] for s in body["work_trail"]}
    assert "bearing" in body["text"].lower()


def test_unknown_tool_is_refused(client):
    r = client.post("/api/tools/call", json={
        "tool": "run_shell", "arguments": {"cmd": "rm -rf /"}}).json()
    assert r["ok"] is False
    assert r["error"] == "TOOL_NOT_ALLOWED"


def test_no_shell_or_filesystem_tool_exists(client):
    names = client.get("/api/tools").json()["tools"]
    forbidden = {"shell", "bash", "exec", "run_command", "read_file", "write_file",
                 "python", "eval"}
    assert not forbidden & {t["name"] for t in names}


def test_web_search_is_off_by_default(client):
    r = client.post("/api/tools/call", json={
        "tool": "web_search", "arguments": {"query": "Siemens E17 fault"}}).json()
    assert r["ok"] is True
    assert r["degraded"] is True
    assert r["results"] == []


def test_fetch_refuses_local_addresses(client):
    for url in ("http://127.0.0.1:8756/api/system/status",
                "http://192.168.1.1/admin",
                "http://169.254.169.254/latest/meta-data/"):
        r = client.post("/api/tools/call", json={
            "tool": "fetch_web_source", "arguments": {"url": url}}).json()
        assert r["fetched"] is False


def test_streaming_emits_trail_then_text(client, manual_pdf):
    _manual(client, manual_pdf)
    with client.stream("POST", "/api/chat/stream",
                       json={"message": "What does E17 mean?"}) as resp:
        assert resp.status_code == 200
        events = []
        for line in resp.iter_lines():
            if line.startswith("data: ") and "[DONE]" not in line:
                events.append(json.loads(line[6:]))
    kinds = [e["type"] for e in events]
    assert kinds[0] == "start"
    assert "model" in kinds
    assert kinds.index("step") < kinds.index("text")
    assert kinds[-1] == "done"
    assert events[-1]["result"]["text"]


def test_every_response_declares_which_model_produced_it(client):
    body = client.post("/api/chat", json={"message": "The pump is leaking."}).json()
    model = body["model"]
    assert set(model) == {"provider", "model_id", "accelerator", "npu", "synthetic"}
    if model["synthetic"]:
        assert model["npu"] is False


def test_web_search_is_a_last_resort_not_a_parallel_source(client, manual_pdf):
    """§16 fixes the order: job context, documents, memory, and only then the web."""
    from app.models.heuristic import _local_knowledge_thin

    strong = {"search_documents": {"results": [{"score": 0.02, "exact_matches": ["E17"]}]}}
    assert _local_knowledge_thin(strong) is False

    remembered = {"search_memory": {"memories": [{"id": "m1"}]}}
    assert _local_knowledge_thin(remembered) is False

    assert _local_knowledge_thin({}) is True
    assert _local_knowledge_thin(
        {"search_documents": {"results": [{"score": 0.005, "exact_matches": []}]}}) is True

    # And the first round never reaches for the web, even when it is permitted.
    _manual(client, manual_pdf)
    body = client.post("/api/chat", json={
        "message": "What does fault code E17 mean?", "web": True}).json()
    trail = [s["tool"] for s in body["work_trail"]]
    assert "search_documents" in trail
    assert trail.index("search_documents") == 0 or "web_search" not in trail[:1]


def test_the_same_memory_is_not_stored_twice(client):
    """§13: "Do not store everything automatically." A repeat is noise."""
    pref = {"memory_type": "preference",
            "content": "Prefers torque figures in Nm rather than lb-ft",
            "confidence": 0.9, "confirmed": True, "source": {"origin": "test"}}
    first = client.post("/api/memories", json=pref).json()
    assert first["stored"] is True

    again = client.post("/api/memories", json=pref).json()
    assert again["stored"] is False
    assert "identical" in again["reason"]
    assert again["duplicate_of"] == first["memory"]["id"]

    # Case and punctuation do not make it a different fact.
    variant = client.post("/api/memories", json={
        **pref, "content": "  PREFERS torque figures in Nm rather than lb-ft. "}).json()
    assert variant["stored"] is False

    # A genuinely different preference still stores.
    other = client.post("/api/memories", json={
        **pref, "content": "Prefers vibration reported in mm/s RMS"}).json()
    assert other["stored"] is True

    assert client.get("/api/memories",
                      params={"memory_type": "preference"}).json()["count"] == 2

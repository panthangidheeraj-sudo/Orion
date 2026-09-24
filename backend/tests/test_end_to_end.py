"""Phase 10 — the §27 scenario that matters most: the same machine, twice.

This walks the whole loop the specification describes —
SEE → RETRIEVE → REASON → VERIFY → GUIDE → REMEMBER — across two separate
visits, and checks that the second visit genuinely benefits from the first.
"""

from __future__ import annotations


def test_same_machine_across_two_sessions(client, manual_pdf, photo_bytes):
    # ---- setup: the vault has the manual for this machine
    client.post("/api/documents/upload", files={
        "file": ("CNC-M04 Service Manual.pdf", manual_pdf, "application/pdf")})

    machine = client.post("/api/machines", json={
        "name": "CNC Motor #04", "manufacturer": "Siemens",
        "model": "CNC-M04", "serial_number": "SN-99123"}).json()

    # ================= VISIT ONE =================
    job = client.post("/api/jobs", json={
        "title": "Overheating and vibration", "machine_id": machine["id"]}).json()
    insp = client.post("/api/inspections",
                       json={"job_id": job["id"], "mode": "photo"}).json()

    first = client.post("/api/photo/analyze", files={
        "file": ("motor.jpg", photo_bytes, "image/jpeg")},
        data={"question": "The motor is overheating and vibrating. Fault code E17 is "
                          "showing. I measured 87 C at the housing.",
              "job_id": job["id"], "inspection_id": insp["id"]}).json()

    # RETRIEVE: it went to the manual, and REASON: it used what the manual says.
    assert "search_documents" in {s["tool"] for s in first["work_trail"]}
    assert "thermal overload" in first["text"].lower()
    # VERIFY: the only figure it states is the one the technician supplied.
    assert "87" in first["text"]
    # GUIDE: concrete next tests, and a hazard notice for a hot electrical machine.
    next_steps = next(s for s in first["sections"] if s["kind"] == "next")
    assert len(next_steps["items"]) >= 3
    assert first["hazards"]

    # The technician records what they actually did.
    client.post("/api/measurements", json={
        "inspection_id": insp["id"], "name": "temperature", "value": 87.0, "unit": "C"})
    client.post("/api/findings", json={
        "inspection_id": insp["id"],
        "description": "Drive-end bearing shows heat discolouration and play",
        "type": "fault", "confidence": 0.78})

    # REMEMBER: only the confirmed outcome becomes durable.
    stored = client.post("/api/memories", json={
        "memory_type": "repair_action",
        "content": "Confirmed drive-end bearing wear on CNC Motor #04; replaced with "
                   "NSK 6203-2RS and re-torqued the end shield to 24 Nm.",
        "confidence": 0.93, "confirmed": True, "job_id": job["id"],
        "source": {"origin": "technician"}}).json()
    assert stored["stored"] is True

    client.post("/api/measurements", json={
        "inspection_id": insp["id"], "name": "temperature", "value": 61.0, "unit": "C"})
    client.post(f"/api/inspections/{insp['id']}/end")

    # ================= VISIT TWO =================
    second = client.post("/api/chat", json={
        "message": "I'm back at CNC Motor #04. What happened here last time?",
        "job_id": job["id"]}).json()

    tools = {s["tool"] for s in second["work_trail"]}
    assert "get_job_history" in tools
    assert "bearing" in second["text"].lower(), "prior work was not recalled"
    assert second["confidence"] >= first["confidence"] - 0.2

    # ---- the report is built from what was recorded, and nothing else
    report = client.post("/api/reports", json={
        "job_id": job["id"],
        "summary": "Bearing wear caused the thermal trip. Replaced; temperature settled at 61 C.",
        "recommendations": ["Re-check vibration after 100 running hours"]}).json()

    md = report["markdown"]
    assert "CNC Motor #04" in md
    assert "SN-99123" in md
    assert "87.0" in md and "61.0" in md
    assert "NSK 6203-2RS" in md
    assert "not a substitute for the manufacturer" in md
    assert report["measurements"] == 2

    listed = client.get("/api/reports", params={"job_id": job["id"]}).json()
    assert listed["count"] == 1


def test_report_on_an_empty_job_invents_nothing(client):
    job = client.post("/api/jobs", json={"title": "Nothing recorded yet"}).json()
    md = client.post("/api/reports", json={"job_id": job["id"]}).json()["markdown"]
    assert "None recorded." in md
    assert "no values have been estimated" in md.lower()


def test_conversation_survives_and_lists(client):
    first = client.post("/api/chat", json={"message": "The press is leaking oil."}).json()
    cid = first["conversation_id"]
    client.post("/api/chat", json={"message": "It drips from the rod end.",
                                   "conversation_id": cid})

    conv = client.get(f"/api/conversations/{cid}").json()
    roles = [m["role"] for m in conv["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]

    listing = client.get("/api/conversations").json()
    assert any(c["id"] == cid for c in listing["conversations"])

    client.delete(f"/api/conversations/{cid}")
    assert client.get(f"/api/conversations/{cid}").status_code == 404


def test_metrics_do_not_invent_npu_numbers(client):
    client.post("/api/chat", json={"message": "The fan is noisy."})
    body = client.get("/api/metrics").json()
    assert body["tool_latency"]
    assert "npu_utilisation" in body["unavailable_metrics"]
    for role, info in body["accelerators"].items():
        if info["synthetic"]:
            assert info["npu"] is False

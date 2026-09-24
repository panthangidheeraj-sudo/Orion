"""The §27 scenarios.

For each fixture the specification asks the same questions: does the agent
observe, read, retrieve, inspect the document visually, remember, express
uncertainty, call the right tools, and produce a usable final answer?

With no detector or OCR export present, several of those come back "I cannot
confirm this visually" — and that is the assertion. An answer that described
the contents of a PCB photograph with no vision model loaded would be a
fabrication, so these tests fail if the agent starts doing that.
"""

from __future__ import annotations

import pytest

from tests import fixtures


def _upload(client, data: bytes, name: str, mime: str = "application/pdf"):
    return client.post("/api/documents/upload",
                       files={"file": (name, data, mime)}).json()


def _photo(client, data: bytes, question: str, **form):
    return client.post("/api/photo/analyze",
                       files={"file": ("frame.jpg", data, "image/jpeg")},
                       data={"question": question, **form}).json()


# --------------------------------------------------------------- image cases

IMAGE_CASES = [
    ("pcb_with_labels", "Which component is at reference C14 and what is its value?"),
    ("motor_nameplate", "Read the nameplate and tell me the rated current."),
    ("motor_assembly", "There is a rumbling noise from this drive. Where do I start?"),
    ("control_panel", "Which contactor feeds the coolant pump?"),
    ("damaged_component", "What has happened to this bearing housing?"),
]


@pytest.mark.parametrize("fixture_name,question", IMAGE_CASES)
def test_image_scenario_states_what_it_cannot_confirm(client, fixture_name, question):
    data = getattr(fixtures, fixture_name)()
    body = _photo(client, data, question)

    # The visual senses were attempted — this is the SEE step, not a skip.
    tools = {s["tool"] for s in body["work_trail"]}
    assert "vision_detect" in tools
    assert "ocr_extract" in tools

    # With no export loaded, both degrade, and the answer must say so rather
    # than describing a photograph it cannot actually read.
    assert "vision_detect" in body["degraded_tools"]
    assert "ocr_extract" in body["degraded_tools"]

    observed = next(s for s in body["sections"] if s["kind"] == "observed")
    joined = " ".join(observed["items"]).lower()
    assert "no detector or ocr result is available" in joined

    # It still has to be useful: a next step and an honest confidence.
    assert any(s["kind"] == "next" and s["items"] for s in body["sections"])
    assert body["confidence"] is not None and body["confidence"] < 0.7
    assert body["model"]["synthetic"] is True


def test_poor_frames_are_described_honestly(client):
    blurred = _photo(client, fixtures.blurred_frame(), "What am I looking at?")
    observed = " ".join(i for s in blurred["sections"]
                        if s["kind"] == "observed" for i in s["items"]).lower()
    assert "low in edge detail" in observed

    dark = _photo(client, fixtures.dark_frame(), "Can you read this label?")
    observed = " ".join(i for s in dark["sections"]
                        if s["kind"] == "observed" for i in s["items"]).lower()
    assert "underexposed" in observed


# ------------------------------------------------------------ document cases

def test_text_only_manual_is_retrieved_and_quoted(client):
    _upload(client, fixtures.text_only_manual(), "CNC-M04 manual.pdf")
    body = client.post("/api/chat", json={
        "message": "What does fault code E17 mean?"}).json()
    assert "thermal overload" in body["text"].lower()
    refs = [r for r in body["refs"] if r["kind"] == "document"]
    assert refs and refs[0]["page"] == 2


def test_diagram_heavy_manual_opens_the_page_as_an_image(client):
    doc = _upload(client, fixtures.diagram_heavy_manual(), "Diagrams.pdf")
    assert doc["pages_rendered"] == 3

    body = client.post("/api/chat", json={
        "message": "Where are the thermistor terminals on the terminal layout?"}).json()

    # A spatial question about a figure must reach the visual brain.
    assert "get_document_page" in {s["tool"] for s in body["work_trail"]}
    page_refs = [r for r in body["refs"] if r["kind"] == "document_page"]
    assert page_refs, "the agent cited no page image for a question about a figure"

    # And the page image is genuinely servable.
    img = client.get(f"/api/documents/{doc['document_id']}/pages/{page_refs[0]['page']}")
    assert img.status_code == 200 and len(img.content) > 1000


def test_wiring_schematic_is_ingested_and_searchable(client):
    doc = _upload(client, fixtures.wiring_schematic(), "Schematic 4412-B.pdf")
    assert doc["pages_rendered"] == 1
    hits = client.post("/api/documents/search",
                       json={"query": "thermistor loop X4"}).json()["results"]
    assert hits and "X4" in hits[0]["content"]


def test_multipage_manual_finds_the_one_relevant_page(client):
    _upload(client, fixtures.multipage_service_manual(24), "Service manual.pdf")
    hits = client.post("/api/documents/search",
                       json={"query": "P09 coolant flow switch FS1", "top_k": 3}).json()
    assert hits["count"] >= 1
    assert hits["results"][0]["page_start"] == 17, \
        f"cited page {hits['results'][0]['page_start']}, the coolant section is page 17"

    greasing = client.post("/api/documents/search",
                           json={"query": "how often do I regrease the drive end bearing",
                                 "top_k": 3}).json()["results"]
    assert greasing[0]["page_start"] == 11


def test_the_agent_picks_the_right_document_out_of_several(client):
    _upload(client, fixtures.text_only_manual(), "CNC-M04 manual.pdf")
    _upload(client, fixtures.wiring_schematic(), "Schematic 4412-B.pdf")
    _upload(client, fixtures.multipage_service_manual(24), "Service manual.pdf")

    body = client.post("/api/chat", json={
        "message": "Fault code P09 is showing. What is it?"}).json()
    refs = [r for r in body["refs"] if r["kind"] in ("document", "document_page")]
    assert refs, "no document was cited"
    assert refs[0]["filename"] == "Service manual.pdf"


def test_uncertainty_is_expressed_when_nothing_is_known(client):
    """An unrecognised symptom must produce "Unknown", not a confident guess."""
    body = client.post("/api/chat", json={
        "message": "The flange on the zorp unit is behaving oddly."}).json()
    items = " ".join(i for s in body["sections"] for i in s["items"]).lower()
    assert "unknown" in items
    assert "does not match a recognised pattern" in items
    assert body["confidence"] < 0.5
    assert body["confidence_label"] in ("Needs evidence", "Weak evidence")


def test_a_recognised_symptom_still_admits_it_has_no_evidence(client):
    """Matching a symptom pattern is not the same as having seen the machine."""
    body = client.post("/api/chat", json={
        "message": "There is a grinding noise from the drive."}).json()
    observed = " ".join(i for s in body["sections"]
                        if s["kind"] == "observed" for i in s["items"]).lower()
    assert "no sensor, image or document evidence" in observed
    assert "general guidance only" in observed
    assert body["confidence"] < 0.6


def test_every_scenario_has_a_fixture():
    """§27 lists ten. None may quietly go missing."""
    for name in fixtures.SCENARIOS:
        if name == "two_sessions":
            continue  # exercised in test_end_to_end.py
        assert hasattr(fixtures, name), f"§27 scenario without a fixture: {name}"

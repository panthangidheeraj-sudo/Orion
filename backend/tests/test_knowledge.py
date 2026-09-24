"""Phases 3–4 — document ingest, the two representations, and retrieval."""

from __future__ import annotations

import io


def _upload(client, manual_pdf, name="CNC-M04 Service Manual.pdf"):
    return client.post("/api/documents/upload",
                       files={"file": (name, manual_pdf, "application/pdf")}).json()


def test_ingest_builds_both_representations(client, manual_pdf):
    body = _upload(client, manual_pdf)
    assert body["state"] == "ready"
    assert body["page_count"] == 4
    # Text brain
    assert body["index"]["chunks"] > 0
    assert body["extraction"]["total_chars"] > 200
    # Visual brain (§11): every page rendered to an image
    assert body["pages_rendered"] == 4

    page = client.get(f"/api/documents/{body['document_id']}/pages/2")
    assert page.status_code == 200
    assert page.headers["content-type"] == "image/png"
    assert len(page.content) > 1000


def test_retrieval_cites_the_page_the_answer_is_printed_on(client, manual_pdf):
    _upload(client, manual_pdf)
    cases = {
        "what does fault code E17 mean": 2,
        "which bearing is fitted at the drive end": 3,
        "what is the rated current on the nameplate": 4,
        "what must I do before removing the terminal cover": 1,
    }
    for query, expected_page in cases.items():
        hits = client.post("/api/documents/search",
                           json={"query": query, "top_k": 2}).json()["results"]
        assert hits, f"no hit for: {query}"
        assert hits[0]["page_start"] == expected_page, \
            f"{query!r} cited page {hits[0]['page_start']}, expected {expected_page}"


def test_exact_technical_token_is_not_buried(client, manual_pdf):
    _upload(client, manual_pdf)
    hits = client.post("/api/documents/search",
                       json={"query": "E17"}).json()["results"]
    assert "E17" in hits[0]["exact_matches"]


def test_unsupported_upload_is_refused_by_content_not_extension(client):
    # An executable renamed to .pdf must not be accepted.
    payload = b"MZ\x90\x00" + b"\x00" * 200
    r = client.post("/api/documents/upload",
                    files={"file": ("payload.pdf", payload, "application/pdf")})
    assert r.status_code == 415
    assert r.json()["error"] == "UNSUPPORTED_MEDIA"


def test_page_request_outside_the_document_is_not_found(client, manual_pdf):
    doc = _upload(client, manual_pdf)
    assert client.get(f"/api/documents/{doc['document_id']}/pages/99").status_code == 404


def test_delete_removes_chunks_and_vectors(client, manual_pdf):
    from app.memory import vector_store as vs

    doc = _upload(client, manual_pdf)
    assert vs.counts().get("document_chunk", 0) > 0
    client.delete(f"/api/documents/{doc['document_id']}")
    assert vs.counts().get("document_chunk", 0) == 0
    assert client.post("/api/documents/search",
                       json={"query": "E17"}).json()["count"] == 0


def test_plain_text_and_markdown_are_indexed(client):
    body = client.post("/api/documents/upload", files={
        "file": ("notes.md", b"# Panel notes\n\nTerminal X4 feeds the coolant pump contactor.",
                 "text/markdown")}).json()
    assert body["index"]["chunks"] >= 1
    hits = client.post("/api/documents/search",
                       json={"query": "coolant pump contactor"}).json()["results"]
    assert hits and "X4" in hits[0]["content"]


def test_irrelevant_passages_are_not_returned_as_evidence(client, manual_pdf):
    """A passage sharing no word with the question is not evidence.

    Ranking can always order something. Presenting the top of a bad ranking as
    a citation sends the technician to a page that does not answer them, which
    is worse than saying the manuals do not cover it.
    """
    from tests import fixtures

    _upload(client, fixtures.multipage_service_manual(24), "Service manual.pdf")
    _upload(client, fixtures.wiring_schematic(), "Schematic.pdf")

    r = client.post("/api/documents/search",
                    json={"query": "hydraulic accumulator precharge nitrogen",
                          "top_k": 5}).json()
    assert r["irrelevant_dropped"] > 0, "nothing was filtered from an unrelated query"
    for hit in r["results"]:
        assert hit["term_coverage"] > 0 or hit["exact_matches"], hit


def test_retrieval_does_not_let_one_document_take_every_slot(client):
    from tests import fixtures

    _upload(client, fixtures.text_only_manual(), "CNC-M04 manual.pdf")
    _upload(client, fixtures.multipage_service_manual(24), "Service manual.pdf")
    _upload(client, fixtures.wiring_schematic(), "Schematic.pdf")

    hits = client.post("/api/documents/search",
                       json={"query": "motor terminal bearing", "top_k": 5}).json()["results"]
    names = [h["filename"] for h in hits]
    assert len(set(names)) >= 2, names
    assert max(names.count(n) for n in set(names)) <= 2, names


def test_top_hit_is_right_across_a_multi_document_vault(client):
    """Precision has to survive a realistic vault, not just one manual."""
    from tests import fixtures

    _upload(client, fixtures.text_only_manual(), "CNC-M04 manual.pdf")
    _upload(client, fixtures.diagram_heavy_manual(), "Diagrams.pdf")
    _upload(client, fixtures.wiring_schematic(), "Schematic 4412-B.pdf")
    _upload(client, fixtures.multipage_service_manual(24), "Service manual.pdf")
    client.post("/api/documents/upload", files={
        "file": ("panel notes.md",
                 b"# Panel notes\n\nTerminal X4 feeds the coolant pump contactor KM3.",
                 "text/markdown")})

    cases = {
        "what does fault code E17 mean": ("CNC-M04 manual.pdf", 2),
        "which bearing is fitted at the drive end": ("CNC-M04 manual.pdf", 3),
        "what is the rated current on the nameplate": ("CNC-M04 manual.pdf", 4),
        "what must I do before removing the terminal cover": ("CNC-M04 manual.pdf", 1),
        "where are the thermistor terminals on the layout": ("Diagrams.pdf", 3),
        "how often do I regrease the drive end bearing": ("Service manual.pdf", 11),
        "P09 coolant flow switch FS1": ("Service manual.pdf", 17),
    }
    for query, (doc, page) in cases.items():
        top = client.post("/api/documents/search",
                          json={"query": query, "top_k": 3}).json()["results"][0]
        assert (top["filename"], top["page_start"]) == (doc, page), \
            f"{query!r} -> {top['filename']} p{top['page_start']}, expected {doc} p{page}"

"""Ordinary conversation (§1).

A field assistant that answers "hi" with "I need a bit more before I can narrow
this down" is behaving like a form. These tests hold the line on the two things
that matters: a chat turn gets a plain reply with none of the diagnostic
furniture, and a message that only *looks* chatty still reaches the agent loop.
"""

from __future__ import annotations

import pytest

from app.agent.conversation import classify

CHAT = [
    ("hi", "greeting"), ("Hello", "greeting"), ("hey there", "greeting"),
    ("good morning", "greeting"), ("yo", "greeting"),
    ("thanks", "thanks"), ("thank you!", "thanks"), ("cheers", "thanks"),
    ("bye", "farewell"), ("that's all", "farewell"), ("all done", "farewell"),
    ("ok", "acknowledgement"), ("got it", "acknowledgement"), ("yes", "acknowledgement"),
    ("what can you do?", "capability"), ("who are you", "capability"),
    ("help", "capability"), ("how does this work", "capability"),
    ("how are you", "smalltalk"), ("you there?", "smalltalk"),
    ("are you chatgpt", "identity"), ("do you run locally", "identity"),
]

# These read conversationally but are work, and must reach the agent loop.
WORK = [
    "hi, the motor is overheating",
    "thanks - but the bearing is still grinding",
    "ok so what does E17 mean",
    "yes it is still tripping the breaker",
    "what can you do about the vibration",
    "the pump is leaking",
    "I measured 87 C",
    "hello, can you read this nameplate",
]


@pytest.mark.parametrize("text,intent", CHAT)
def test_conversational_messages_are_recognised(text, intent):
    assert classify(text) == intent


@pytest.mark.parametrize("text", WORK)
def test_work_is_never_mistaken_for_chat(text):
    assert classify(text) is None, f"{text!r} was swallowed as conversation"


def test_a_greeting_gets_a_plain_reply(client):
    body = client.post("/api/chat", json={"message": "hi"}).json()

    assert body["conversational"] is True
    assert body["intent"] == "greeting"
    assert body["text"].lower().startswith("hello")

    # None of the diagnostic furniture belongs on a greeting.
    assert body["sections"] == []
    assert body["notice"] is None
    assert body["confidence"] is None
    assert body["refs"] == []
    assert body["hazards"] == []

    # No suggestion chips either: the reply already says what to do next, and
    # a row of buttons under "hello" is the product showing off.
    assert body["follow_ups"] == []


def test_a_greeting_runs_no_tools_at_all(client, manual_pdf):
    """§8's efficiency argument applies to idle chat too."""
    client.post("/api/documents/upload", files={
        "file": ("manual.pdf", manual_pdf, "application/pdf")})

    body = client.post("/api/chat", json={"message": "hello"}).json()
    assert body["work_trail"] == [], body["work_trail"]
    assert body["evidence_keys"] == []


def test_capability_answer_describes_what_is_actually_there(client, manual_pdf):
    empty = client.post("/api/chat", json={"message": "what can you do?"}).json()
    assert "nothing is in the vault yet" in empty["text"].lower()

    client.post("/api/documents/upload", files={
        "file": ("manual.pdf", manual_pdf, "application/pdf")})
    loaded = client.post("/api/chat", json={"message": "what can you do?"}).json()
    assert "nothing is in the vault yet" not in loaded["text"].lower()
    assert "cite the page" in loaded["text"]


def test_identity_answer_is_honest_about_the_engine(client):
    body = client.post("/api/chat", json={"message": "are you chatgpt?"}).json()
    text = body["text"].lower()
    assert "visionfield" in text
    if body["model"]["synthetic"]:
        assert "stand-in" in text
        assert "not a language model" in text


def test_a_greeting_with_a_symptom_still_gets_the_full_loop(client, manual_pdf):
    client.post("/api/documents/upload", files={
        "file": ("manual.pdf", manual_pdf, "application/pdf")})

    body = client.post("/api/chat", json={
        "message": "hi, fault code E17 is showing on the drive"}).json()

    assert body.get("conversational") is not True
    assert "search_documents" in {s["tool"] for s in body["work_trail"]}
    assert "thermal overload" in body["text"].lower()


def test_an_open_job_is_mentioned_in_the_greeting(client):
    job = client.post("/api/jobs", json={"title": "Overheating on line 4"}).json()
    body = client.post("/api/chat", json={
        "message": "hi", "job_id": job["id"]}).json()
    assert "Overheating on line 4" in body["text"]


def test_conversation_is_persisted_like_any_other_turn(client):
    first = client.post("/api/chat", json={"message": "hi"}).json()
    conv = client.get(f"/api/conversations/{first['conversation_id']}").json()
    roles = [m["role"] for m in conv["messages"]]
    assert roles == ["user", "assistant"]
    assert conv["messages"][1]["metadata"]["conversational"] is True


def test_a_photo_is_never_small_talk(client, photo_bytes):
    """"What is this?" over a picture of a bearing housing is work."""
    body = client.post("/api/photo/analyze",
                       files={"file": ("frame.jpg", photo_bytes, "image/jpeg")},
                       data={"question": "What is this?"}).json()

    assert body.get("conversational") is not True
    assert "vision_detect" in {s["tool"] for s in body["work_trail"]}
    assert body["sections"], "a photo turn came back with no analysis"

"""The model-driven router, and what each routing decision does to a turn.

The scripted double in tests/llm_double.py stands in for the model: these
tests check the *pipeline* — that the model is asked, with the right context
and a strict schema; that its decision is honoured; that a bad or missing
model degrades honestly; and that the safety gate stays independent. How well
a real model classifies is checked against a real server with
scripts/router_qa.py.
"""

from __future__ import annotations

import importlib
import json

import pytest

from tests.llm_double import decision

FURNITURE = ("sections", "work_trail", "follow_ups", "refs")


def _chat(client, message, **kw):
    return client.post("/api/chat", json={"message": message, **kw}).json()


def _assert_plain(body):
    for key in FURNITURE:
        assert body[key] == [], f"a {body['kind']} turn carried {key}"
    assert body["confidence"] is None and body["confidence_label"] is None


# ------------------------------------------------------------ no old system

def test_the_regex_router_is_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.agent.conversation")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.models.heuristic")


# -------------------------------------------------------------- no model

def test_without_a_model_orion_does_not_pretend(client):
    body = _chat(client, "my motor is vibrating")
    assert body["kind"] == "fallback"
    assert body["engine_available"] is False
    assert body["text"] == "I’m here. Tell me a little more about what you need."
    _assert_plain(body)
    assert body["notice"] is None


def test_without_a_model_the_safety_gate_still_runs(client):
    body = _chat(client, "there are sparks from the panel")
    assert body["kind"] == "fallback"
    assert body["notice"]["level"] == "safety"
    assert body["notice"]["title"] == "Get safe first"
    assert "arcing" in body["hazards"]
    assert "get yourself safe" in body["text"]


# ---------------------------------------------------------------- schema

def test_schema_is_enforced_strictly():
    from app.agent.router import _extract_json, validate

    good = decision("technical", 0.8)
    assert validate(good)["intent"] == "technical"
    assert validate({**good, "intent": "diagnose"}) is None
    assert validate({**good, "confidence": 1.4}) is None
    assert validate({**good, "confidence": True}) is None
    assert validate({**good, "requires_safety_gate": "no"}) is None
    assert validate({**good, "extra": 1}) is None
    assert validate({k: v for k, v in good.items() if k != "reason"}) is None
    wrapped = "<think>hmm</think>\n```json\n" + json.dumps(good) + "\n```"
    assert validate(_extract_json(wrapped)) == validate(good)


def test_router_asks_for_structured_output(client, llm):
    _chat(client, "hellooo")
    ctx = llm.route_calls[0]["context"]
    assert ctx["response_format"]["properties"]["intent"]["enum"] == \
        ["conversation", "technical", "ambiguous"]
    assert llm.route_calls[0]["tools"] == []


def test_openai_compat_payload_carries_the_json_schema():
    from app.agent.router import ROUTE_SCHEMA
    from app.models.qwen_vl import LocalOpenAICompatProvider

    body = LocalOpenAICompatProvider()._payload(
        [{"role": "user", "content": "x"}], None, None, False,
        {"purpose": "route", "response_format": ROUTE_SCHEMA, "temperature": 0.0})
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == ROUTE_SCHEMA
    assert body["temperature"] == 0.0


def test_off_schema_output_is_retried_then_falls_back(client, llm):
    llm.route_fn = lambda msg, prompt: "Sounds technical to me!"
    body = _chat(client, "my pump is leaking")
    assert body["kind"] == "fallback" and body["engine_available"] is False
    assert len(llm.route_calls) == 2           # one corrective retry, no more
    assert not any(c["purpose"] == "technical" for c in llm.calls)


def test_one_bad_answer_is_recovered_by_the_retry(client, llm):
    answers = iter(["technical", decision("conversation")])
    llm.route_fn = lambda msg, prompt: next(answers)
    body = _chat(client, "do you like cats?")
    assert body["kind"] == "conversation"


# ------------------------------------------------------------ behaviours

def test_conversation_gets_a_plain_model_reply(client, llm):
    llm.route_fn = lambda msg, prompt: decision("conversation")
    llm.chat_fn = lambda messages, ctx: "I do — cats have excellent opinions."
    body = _chat(client, "do you like cats?")
    assert body["kind"] == "conversation" and body["conversational"] is True
    assert body["text"] == "I do — cats have excellent opinions."
    _assert_plain(body)
    chat_call = next(c for c in llm.calls if c["purpose"] == "conversation")
    assert chat_call["tools"] == []
    assert "not a diagnostic request" in chat_call["messages"][0]["content"]


def test_ambiguous_gets_a_natural_clarifying_question(client, llm):
    llm.route_fn = lambda msg, prompt: decision("ambiguous", 0.7)
    llm.chat_fn = lambda messages, ctx: ("Sure. Tell me what's going wrong and what you "
                                         "were expecting it to do.")
    body = _chat(client, "something is wrong")
    assert body["kind"] == "clarify"
    assert body["text"].startswith("Sure.")
    _assert_plain(body)
    call = next(c for c in llm.calls if c["purpose"] == "ambiguous")
    assert "hasn't said what with" in call["messages"][0]["content"]


def test_technical_runs_the_workflow(client, llm, manual_pdf):
    client.post("/api/documents/upload",
                files={"file": ("CNC-M04 manual.pdf", manual_pdf, "application/pdf")})
    body = _chat(client, "fault code E17 is showing on the drive")
    assert body["kind"] == "diagnosis" and body["conversational"] is False
    assert "search_documents" in {s["tool"] for s in body["work_trail"]}
    assert body["sections"] and body["confidence"] is not None
    assert any(r["kind"] == "document" for r in body["refs"])


def test_technical_model_can_ask_one_specific_question(client, llm):
    llm.technical_fn = lambda messages, images, tools, ctx: {
        "text": "Got it. Is the vibration strongest at the drive end, the fan end or the "
                "mounting base?", "tool_calls": []}
    body = _chat(client, "my motor is vibrating")
    assert body["kind"] == "clarify"
    assert "drive end" in body["text"]
    assert body["sections"] == [] and body["confidence"] is None
    assert body["follow_ups"] == []
    assert "I need more information" not in body["text"]


# -------------------------------------------------------------- context

def test_router_sees_history_and_the_turn_is_not_duplicated(client, llm):
    def route(msg, prompt):
        # The double "reads" the transcript, as a model would.
        transcript = prompt.split("Recent conversation:")[1].split("Latest message:")[0]
        return decision("technical" if "motor" in (msg + transcript).lower()
                        else "conversation")

    llm.route_fn = route
    first = _chat(client, "My motor is vibrating.")
    cid = first["conversation_id"]
    second = _chat(client, "yeah, exactly.", conversation_id=cid)

    assert second["intent"] == "technical"
    prompt = llm.route_calls[-1]["messages"][-1]["content"]
    transcript = prompt.split("Recent conversation:")[1].split("Latest message:")[0]
    assert "USER: My motor is vibrating." in transcript
    assert "ASSISTANT:" in transcript
    assert "yeah, exactly." not in transcript     # only in "Latest message"


def test_multi_turn_transitions(client, llm):
    script = {"Do you like cats?": "conversation",
              "Anyway, my pump is leaking.": "technical",
              "haha ok, thanks!": "conversation",
              "back to it — the seal is weeping at the rod end": "technical"}
    llm.route_fn = lambda msg, prompt: decision(script[msg])
    cid = None
    kinds = []
    for message in script:
        body = _chat(client, message, **({"conversation_id": cid} if cid else {}))
        cid = body["conversation_id"]
        kinds.append(body["kind"])
    assert kinds == ["conversation", "diagnosis", "conversation", "diagnosis"]
    # Every turn went through the router, with the growing transcript.
    assert len(llm.route_calls) == 4
    last = llm.route_calls[-1]["messages"][-1]["content"]
    assert "Anyway, my pump is leaking." in last and "haha ok, thanks!" in last


def test_attachments_reach_the_router(client, llm, photo_bytes):
    _chat(client, "summarise this", attachments=[{"kind": "pdf", "name": "manual.pdf"}])
    assert "pdf (manual.pdf)" in llm.route_calls[-1]["messages"][-1]["content"]

    client.post("/api/photo/analyze", files={"file": ("m.jpg", photo_bytes, "image/jpeg")},
                data={"question": "what do you think?"})
    assert "Attached to this message: image" in llm.route_calls[-1]["messages"][-1]["content"]


def test_an_attached_photo_reaches_the_model_on_a_technical_turn(client, llm, photo_bytes):
    body = client.post("/api/photo/analyze",
                       files={"file": ("m.jpg", photo_bytes, "image/jpeg")},
                       data={"question": "what does this image show?"}).json()
    tools = {s["tool"] for s in body["work_trail"]}
    assert {"vision_detect", "ocr_extract"} <= tools
    tech = [c for c in llm.calls if c["purpose"] == "technical"]
    assert tech and tech[0]["images"], "the model never saw the photo"


# ---------------------------------------------------------------- safety

def test_safety_first_on_a_technical_turn(client, llm):
    body = _chat(client, "there are sparks from the panel")
    assert body["notice"]["title"] == "Get safe first"
    assert body["hazards"][0] == "arcing"


def test_safety_first_even_when_the_model_calls_it_chat(client, llm):
    llm.route_fn = lambda msg, prompt: decision("conversation")
    llm.chat_fn = lambda messages, ctx: "That's worrying — what happened?"
    body = _chat(client, "lol the socket just gave off sparks")
    assert body["kind"] == "conversation"
    assert body["notice"]["level"] == "safety"


def test_the_model_can_add_caution_but_never_remove_it(client, llm):
    llm.route_fn = lambda msg, prompt: decision("technical", gate=True)
    body = _chat(client, "the guard is off and it's still turning")
    assert body["notice"]["level"] == "safety"


def test_the_rationale_is_never_returned(client, llm):
    llm.route_fn = lambda msg, prompt: decision("conversation", reason="SECRET-RATIONALE")
    body = client.post("/api/chat", json={"message": "hmm"}).text
    assert "SECRET-RATIONALE" not in body

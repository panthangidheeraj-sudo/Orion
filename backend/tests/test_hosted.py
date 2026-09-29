"""The Groq-hosted provider (Render).

The provider is exercised against a fake OpenAI-compatible server mounted with
``httpx.MockTransport`` — real request/response handling, no network. What is
being checked is Orion's side: when the provider may be chosen, what the status
report says (never an NPU, never a stand-in), that the API key stays server-side,
and that text, image and streaming requests are shaped correctly.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List

import httpx
import pytest

KEY = "sk-test-SECRET-1234567890"
BASE = "https://api.groq.com/openai/v1"
MODEL = "qwen/qwen3.8-27b"

ROUTE_CHAT = {"intent": "conversation", "confidence": 0.95, "reason": "greeting",
              "requires_safety_gate": False}


class FakeProvider:
    """Records every request; answers like an OpenAI-compatible server."""

    def __init__(self, models=(MODEL,), models_status=200, key=KEY) -> None:
        self.models, self.models_status, self.key = list(models), models_status, key
        self.requests: List[httpx.Request] = []
        self.bodies: List[Dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("authorization") != f"Bearer {self.key}":
            return httpx.Response(401, json={"error": "bad key"})
        if request.url.path.endswith("/models"):
            if self.models_status != 200:
                return httpx.Response(self.models_status)
            return httpx.Response(200, json={"data": [{"id": m} for m in self.models]})
        body = json.loads(request.content)
        self.bodies.append(body)
        if body.get("stream"):
            chunks = ["Hel", "lo ", "there"]
            sse = "".join(
                "data: " + json.dumps({"choices": [{"delta": {"content": c}}]}) + "\n\n"
                for c in chunks) + "data: [DONE]\n\n"
            return httpx.Response(200, content=sse.encode(),
                                  headers={"content-type": "text/event-stream"})
        if body.get("response_format"):
            text = json.dumps(ROUTE_CHAT)
        else:
            has_image = any(isinstance(m.get("content"), list) and any(
                p.get("type") == "image_url" for p in m["content"]) for m in body["messages"])
            text = "I can see the image." if has_image else "Hello from the hosted model."
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}],
                                         "usage": {"total_tokens": 5}})


@pytest.fixture
def hosted(monkeypatch, isolated_data):
    """Configure the hosted provider and route httpx to a fake server."""
    from app.config import settings
    from app.models.registry import registry

    fake = FakeProvider()
    real_async, real_get, real_post = httpx.AsyncClient, httpx.get, httpx.post

    def async_client(*a, **k):
        k["transport"] = httpx.MockTransport(fake.handler)
        return real_async(*a, **k)

    def get(url, **k):
        with httpx.Client(transport=httpx.MockTransport(fake.handler)) as c:
            return c.get(url, **{x: y for x, y in k.items() if x in ("headers", "timeout")})

    def post(url, **k):
        with httpx.Client(transport=httpx.MockTransport(fake.handler)) as c:
            return c.post(url, **{x: y for x, y in k.items() if x in ("headers", "timeout", "json")})

    monkeypatch.setattr(httpx, "AsyncClient", async_client)
    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(settings, "reasoning_provider", "hosted-groq", raising=False)
    monkeypatch.setattr(settings, "hosted_llm_base_url", BASE, raising=False)
    monkeypatch.setattr(settings, "hosted_llm_api_key", KEY, raising=False)
    monkeypatch.setattr(settings, "hosted_llm_model", MODEL, raising=False)
    registry.reload()
    yield fake
    registry.reload()


def test_unconfigured_is_unavailable_never_a_stand_in(client, monkeypatch):
    from app.config import settings
    from app.models.registry import registry

    monkeypatch.setattr(settings, "reasoning_provider", "hosted-groq", raising=False)
    monkeypatch.setattr(settings, "hosted_llm_api_key", "", raising=False)
    monkeypatch.setattr(settings, "hosted_llm_base_url", "", raising=False)
    registry.reload()
    body = client.get("/api/models/status").json()
    ai = body["ai"]
    assert ai["mode"] == "unavailable" and ai["status"] != "ready"
    assert ai["npu"] is False and ai["hosted"] is False and ai["synthetic"] is False
    assert "not configured" in (ai["reason"] or "") or "not configured" in json.dumps(body["roles"]["reasoning"])
    # And a chat turn says so instead of inventing an answer.
    r = client.post("/api/chat", json={"message": "hello"})
    assert r.status_code == 200
    assert "Hello from the hosted model" not in r.text


def test_status_reports_hosted_honestly(client, hosted):
    body = client.get("/api/models/status").json()
    ai = body["ai"]
    assert ai == {**ai, "mode": "hosted", "hosted": True, "npu": False, "synthetic": False,
                  "provider": "hosted-groq", "model_id": MODEL, "accelerator": "remote",
                  "status": "ready"}
    role = body["roles"]["reasoning"]
    assert role["npu"] is False and role["hosted"] is True
    assert body["summary"]["npu_claim"] is False
    assert "reasoning" not in body["summary"]["npu_accelerated"]
    # The key and the provider URL never appear in a public response.
    blob = json.dumps(body)
    assert KEY not in blob and "api.groq.com" not in blob


def test_npu_is_forced_off_for_any_hosted_health():
    from app.models.base import ModelHealth
    h = ModelHealth(role="reasoning", provider="x", model_id="m", npu=True, hosted=True)
    assert h.to_dict()["npu"] is False


def test_wrong_key_is_unavailable_and_never_leaks_it(client, hosted, monkeypatch):
    from app.config import settings
    from app.models.registry import registry
    monkeypatch.setattr(settings, "hosted_llm_api_key", "sk-wrong-key-000", raising=False)
    registry.reload()
    body = client.get("/api/models/status").json()
    assert body["ai"]["mode"] == "unavailable"
    assert "rejected the API key" in body["ai"]["reason"]
    assert "sk-wrong-key-000" not in json.dumps(body)


def test_model_name_is_config_not_hardcoded(client, hosted, monkeypatch):
    from app.config import settings
    from app.models.registry import registry
    hosted.models = ["some-vendor/other-model"]
    monkeypatch.setattr(settings, "hosted_llm_model", "some-vendor/other-model", raising=False)
    registry.reload()
    ai = client.get("/api/models/status").json()["ai"]
    assert ai["mode"] == "hosted" and ai["model_id"] == "some-vendor/other-model"
    monkeypatch.setattr(settings, "hosted_llm_model", "", raising=False)
    registry.reload()
    assert "empty" in client.get("/api/models/status").json()["ai"]["reason"]


def test_groq_api_key_env_name_is_accepted(monkeypatch):
    from app.config import Settings
    for name in ("VF_HOSTED_LLM_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv("VF_HOSTED_LLM_API_KEY", raising=False)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.setenv(name, "gsk_test_abc")
        assert Settings(_env_file=None).hosted_llm_api_key == "gsk_test_abc"
    s = Settings(_env_file=None)
    assert s.hosted_llm_base_url == "https://api.groq.com/openai/v1"
    assert s.hosted_llm_model == "qwen/qwen3.8-27b"


def test_quota_exhausted_is_unavailable_honestly(client, hosted):
    def limited(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(429)
        return hosted.handler(request)
    hosted.handler = limited  # type: ignore[assignment]
    from app.models.registry import registry
    registry.reload()
    ai = client.get("/api/models/status").json()["ai"]
    assert ai["mode"] == "unavailable" and "quota" in ai["reason"]
    assert ai["npu"] is False and ai["synthetic"] is False


def test_model_missing_from_provider_is_unavailable(client, hosted):
    hosted.models = ["some/other-model"]
    from app.models.registry import registry
    registry.reload()
    assert client.get("/api/models/status").json()["ai"]["mode"] == "unavailable"


def test_provider_without_model_list_is_proven_by_a_real_call(client, hosted):
    hosted.models_status = 404
    from app.models.registry import registry
    registry.reload()
    assert client.get("/api/models/status").json()["ai"]["mode"] == "hosted"
    assert any(b.get("max_tokens") == 1 for b in hosted.bodies)


def test_https_is_required(client, hosted, monkeypatch):
    from app.config import settings
    from app.models.registry import registry
    monkeypatch.setattr(settings, "hosted_llm_base_url", "http://api.groq.com/v1", raising=False)
    registry.reload()
    assert "https://" in client.get("/api/models/status").json()["ai"]["reason"]


@pytest.mark.asyncio
async def test_text_generation_sends_the_key_server_side(hosted):
    from app.models.registry import registry
    r = registry.reasoning()
    out = await r.generate([{"role": "user", "content": "hi"}])
    assert out["text"] == "Hello from the hosted model."
    assert all(q.headers["authorization"] == f"Bearer {KEY}" for q in hosted.requests)
    assert hosted.bodies[-1]["model"] == MODEL
    # The reasoning is kept out of the reply: none requested, hidden if it happens.
    assert hosted.bodies[-1]["reasoning_effort"] == "none"
    assert hosted.bodies[-1]["reasoning_format"] == "hidden"


@pytest.mark.asyncio
async def test_image_and_text_generation(hosted, tmp_path, photo_bytes):
    from app.models.base import ImageRef
    from app.models.registry import registry
    p = tmp_path / "frame.jpg"
    p.write_bytes(photo_bytes)
    ref = ImageRef(id="img1", path=str(p), width=640, height=480)
    out = await registry.reasoning().generate(
        [{"role": "user", "content": "What is on the nameplate?"}], images=[ref])
    assert out["text"] == "I can see the image."
    content = hosted.bodies[-1]["messages"][-1]["content"]
    assert content[0] == {"type": "text", "text": "What is on the nameplate?"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_streaming(hosted):
    from app.models.registry import registry
    events = [e async for e in registry.reasoning().stream([{"role": "user", "content": "hi"}])]
    assert [e["value"] for e in events if e["type"] == "text"] == ["Hel", "lo ", "there"]
    assert events[-1]["type"] == "done" and events[-1]["value"]["text"] == "Hello there"
    assert hosted.bodies[-1]["stream"] is True


def test_chat_and_sse_through_the_real_pipeline(client, hosted, photo_bytes):
    r = client.post("/api/chat", json={"message": "hello there"})
    assert r.status_code == 200, r.text
    assert "Hello from the hosted model" in r.json()["text"]
    assert r.json()["model"]["hosted"] is True and r.json()["model"]["npu"] is False

    with client.stream("POST", "/api/chat/stream", json={"message": "hello there"}) as s:
        events = [json.loads(l[5:]) for l in s.iter_lines() if l.startswith("data:") and "[DONE]" not in l]
    model_ev = next(e for e in events if e["type"] == "model")
    assert model_ev["hosted"] is True and model_ev["npu"] is False
    assert model_ev["provider"] == "hosted-groq"
    assert any(e["type"] in ("token", "text", "delta", "answer", "done") for e in events)


def test_provider_outage_reports_unavailable_not_a_fake_answer(client, hosted):
    def down(request):
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(503)
        return hosted.handler(request)
    real = hosted.handler
    hosted.handler = down  # type: ignore[assignment]
    # Rebind: the fixture's transports call fake.handler at request time.
    r = client.post("/api/chat", json={"message": "hello there"})
    hosted.handler = real  # type: ignore[assignment]
    assert "Hello from the hosted model" not in r.text


def test_auto_mode_uses_hosted_only_when_configured(client, monkeypatch, hosted):
    from app.config import settings
    from app.models.registry import registry
    monkeypatch.setattr(settings, "reasoning_provider", "auto", raising=False)
    registry.reload()
    assert client.get("/api/models/status").json()["ai"]["provider"] == "hosted-groq"
    monkeypatch.setattr(settings, "hosted_llm_api_key", "", raising=False)
    registry.reload()
    assert client.get("/api/models/status").json()["ai"]["mode"] == "unavailable"


def test_ephemeral_host_adopts_a_client_conversation_id(client, monkeypatch, hosted):
    from app.config import settings
    monkeypatch.setattr(settings, "ephemeral_storage", True, raising=False)
    r = client.post("/api/chat", json={"message": "hello there", "conversation_id": "conv_restored_from_firebase"})
    assert r.status_code == 200, r.text
    monkeypatch.setattr(settings, "ephemeral_storage", False, raising=False)
    r = client.post("/api/chat", json={"message": "hello", "conversation_id": "conv_never_seen_before"})
    assert r.status_code == 404


def test_no_endpoint_ever_returns_the_key_or_provider_url(client, hosted):
    client.post("/api/chat", json={"message": "hello there"})
    for path in ("/api/health", "/api/models/status", "/api/system/status", "/api/metrics",
                 "/openapi.json", "/api/tools", "/api/conversations"):
        r = client.get(path)
        assert KEY not in r.text, path
        assert "api.groq.com" not in r.text, path


def test_photo_turn_reaches_the_hosted_model_as_an_image(client, hosted, photo_bytes):
    r = client.post("/api/photo/analyze", files={"file": ("motor.jpg", photo_bytes, "image/jpeg")},
                    data={"question": "hello, what do you see?"})
    assert r.status_code == 200, r.text
    sent = [b for b in hosted.bodies for m in b["messages"]
            if isinstance(m.get("content"), list)
            and any(p.get("type") == "image_url" for p in m["content"])]
    assert sent, "the photo was never sent to the hosted model"
    assert r.json()["model"]["hosted"] is True


def test_system_status_says_photos_go_to_the_provider_when_hosted(client, hosted):
    ls = client.get("/api/system/status").json()["local_first"]
    assert ls["ai_hosted"] is True and ls["cloud_camera_frames"] is True
    assert ls["cloud_documents"] is False and ls["cloud_audio"] is False


@pytest.mark.asyncio
async def test_at_most_three_images_are_sent(hosted, tmp_path, photo_bytes):
    from app.models.base import ImageRef
    from app.models.registry import registry
    refs = []
    for i in range(5):
        p = tmp_path / f"f{i}.jpg"
        p.write_bytes(photo_bytes)
        refs.append(ImageRef(id=f"i{i}", path=str(p), width=640, height=480))
    await registry.reasoning().generate([{"role": "user", "content": "compare"}], images=refs)
    parts = hosted.bodies[-1]["messages"][-1]["content"]
    assert sum(1 for p in parts if p["type"] == "image_url") == 3


@pytest.mark.asyncio
async def test_a_400_retries_without_optional_parameters(hosted):
    """A model that rejects reasoning_* / response_format still answers."""
    seen = []
    real = hosted.handler

    def picky(request):
        if request.url.path.endswith("/chat/completions"):
            body = json.loads(request.content)
            seen.append(sorted(body))
            if "reasoning_effort" in body:
                return httpx.Response(400, json={"error": "unsupported parameter"})
        return real(request)
    hosted.handler = picky  # type: ignore[assignment]
    from app.models.registry import registry
    out = await registry.reasoning().generate([{"role": "user", "content": "hi"}])
    assert out["text"] == "Hello from the hosted model."
    assert "reasoning_effort" in seen[0] and "reasoning_effort" not in seen[1]


def test_the_snapdragon_provider_is_untouched_and_still_first_in_auto():
    from app.models.registry import _candidates
    names = [n for n, _ in _candidates()["reasoning"]]
    assert names[:2] == ["geniex-qwen3-vl", "hosted-groq"]

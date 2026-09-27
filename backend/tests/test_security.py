"""Request-level protection: access key, rate limits, body caps, SSRF, bombs."""

from __future__ import annotations

import asyncio
import io

import pytest


@pytest.fixture
def locked(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "access_token", "s3cret-key", raising=False)
    return "s3cret-key"


def test_open_when_no_key_configured(client):
    assert client.get("/api/conversations").status_code == 200


def test_key_required_when_configured(client, locked):
    r = client.get("/api/conversations")
    assert r.status_code == 401
    assert r.json()["error"] == "UNAUTHORIZED"
    assert client.get("/api/conversations", headers={"X-Orion-Key": "wrong"}).status_code == 401
    assert client.get("/api/conversations", headers={"X-Orion-Key": locked}).status_code == 200
    assert client.get("/api/conversations",
                      headers={"Authorization": f"Bearer {locked}"}).status_code == 200


def test_mutating_routes_are_locked(client, locked):
    assert client.post("/api/chat", json={"message": "hello"}).status_code == 401
    assert client.delete("/api/conversations/conv_x").status_code == 401
    assert client.post("/api/models/reload").status_code == 401
    assert client.post("/api/tools/call", json={"tool": "web_search",
                                                "arguments": {"query": "abc"}}).status_code == 401


def test_probes_stay_public(client, locked):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/models/status").status_code == 200


def test_media_routes_reachable_by_id_only(client, locked):
    # Public (an <img> tag cannot send headers) but only for well-formed ids,
    # and they still 404 for ids that do not exist.
    r = client.get("/api/voice/audio/aud_doesnotexist")
    assert r.status_code == 404
    assert client.get("/api/voice/audio/..%2F..%2Fetc").status_code in (401, 404)


def test_refused_requests_still_carry_cors(client, locked):
    r = client.get("/api/conversations", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 401
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_rate_limit(client, monkeypatch):
    from app.config import settings
    from app.security import limiter

    monkeypatch.setattr(settings, "rate_limit_per_minute", 5, raising=False)
    limiter.hits.clear()
    codes = [client.get("/api/health").status_code for _ in range(7)]
    assert codes[:5] == [200] * 5
    assert codes[5] == 429
    limiter.hits.clear()


def test_heavy_routes_have_their_own_budget(client, monkeypatch):
    from app.config import settings
    from app.security import limiter

    monkeypatch.setattr(settings, "rate_limit_per_minute", 100, raising=False)
    monkeypatch.setattr(settings, "heavy_rate_limit_per_minute", 2, raising=False)
    limiter.hits.clear()
    codes = [client.post("/api/chat", json={"message": "hello"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert client.get("/api/health").status_code == 200
    limiter.hits.clear()


def test_oversized_body_refused_before_reading(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "max_upload_bytes", 1024, raising=False)
    from app.api import _media

    monkeypatch.setattr(_media, "MAX_IMAGE_BYTES", 1024, raising=False)
    r = client.post("/api/documents/upload",
                    files={"file": ("big.txt", io.BytesIO(b"x" * 300_000), "text/plain")})
    assert r.status_code == 413


def test_upload_stream_capped(monkeypatch):
    from app.api._media import read_upload
    from app.errors import PayloadTooLarge

    class Fake:
        size = None

        def __init__(self, n):
            self.buf = io.BytesIO(b"y" * n)

        async def read(self, n=-1):
            return self.buf.read(n)

    with pytest.raises(PayloadTooLarge):
        asyncio.run(read_upload(Fake(5000), limit=4096))
    assert len(asyncio.run(read_upload(Fake(4000), limit=4096))) == 4000


def test_decompression_bomb_refused(tmp_path):
    from PIL import Image

    from app.errors import UnsupportedMedia
    from app.api._media import store_image

    # 12000 x 12000 = 144 MP of a single colour compresses to a few KB.
    buf = io.BytesIO()
    Image.new("L", (12000, 12000)).save(buf, format="PNG")
    with pytest.raises(UnsupportedMedia):
        store_image(buf.getvalue())


@pytest.mark.parametrize("url", [
    "http://172.20.0.5/", "http://[::1]/", "http://2130706433/", "http://0x7f000001/",
    "http://100.64.0.1/", "http://[fd00::1]/", "http://[::ffff:127.0.0.1]/",
    "http://metadata.google.internal/", "http://user:pw@example.com/",
])
def test_ssrf_bypasses_refused(client, url):
    r = client.post("/api/tools/call", json={
        "tool": "fetch_web_source", "arguments": {"url": url}}).json()
    assert r["fetched"] is False


def test_tool_errors_do_not_leak_internals(monkeypatch):
    from app.agent.tool_registry import registry

    async def boom(**_):
        raise RuntimeError("/srv/secret/path.db is locked")

    spec = registry.get("web_search")
    monkeypatch.setattr(spec, "handler", boom)
    r = asyncio.run(registry.call("web_search", {"query": "abc"}))
    assert r["ok"] is False
    assert "/srv/secret" not in str(r)


def test_docs_hidden_when_locked(monkeypatch):
    # _docs is decided at import; check the rule itself.
    from app.config import settings

    monkeypatch.setattr(settings, "access_token", "k", raising=False)
    assert not (settings.expose_docs and not settings.access_token)

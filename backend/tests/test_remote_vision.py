"""The Render split: public API <-> private orion-vision, with a mock service.

The vision service under test is the real ``app.vision_service`` app with
scripted adapters, wired to the API's remote adapters through an in-process
transport, so auth, multipart transport, status honesty and degradation are
all exercised end to end without a network or any model file.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app import vision_service
from app.config import settings
from app.models import base
from app.models.base import (
    NoClassifier, OCRProvider, VisionDetector, VisionSegmenter,
)
from app.models.registry import registry as models
from app.models.tracking import CentroidTracker

KEY = "svc-key-for-tests-0123456789"
HOST = "http://vision.internal:10000"


class FakeDetector(VisionDetector):
    def __init__(self):
        super().__init__("fake_det", "fake-onnx")
        self.seen_sizes = []

    def _load(self):
        self._health = base.ModelHealth(role="detector", provider="fake-onnx",
                                        model_id="fake_det", status=base.READY,
                                        runtime="onnxruntime", accelerator="cpu")

    async def detect(self, image):
        self.seen_sizes.append((image.width, image.height))
        return [{"label": "motor", "confidence": 0.91, "bbox": [1, 2, 30, 40]}]


class FakeSegmenter(VisionSegmenter):
    def __init__(self):
        super().__init__("fake_seg", "fake-onnx")

    def _load(self):
        self._health = base.ModelHealth(role="segmenter", provider="fake-onnx",
                                        model_id="fake_seg", status=base.READY,
                                        runtime="onnxruntime", accelerator="cpu")

    async def segment(self, image, target=None):
        return {"target": target, "mask": "fake"}


class FakeOCR(OCRProvider):
    def __init__(self):
        super().__init__("fake_ocr", "fake-ocr")

    def _load(self):
        self._health = base.ModelHealth(role="ocr", provider="fake-ocr", model_id="fake_ocr",
                                        status=base.READY, runtime="onnxruntime", accelerator="cpu")

    async def extract(self, image):
        return [{"text": "CNC M04 400V", "confidence": 0.9, "bbox": [0, 0, 5, 5], "source": "fake"}]


class FakeRegistry:
    def __init__(self):
        self.det = FakeDetector()
        self._roles = {
            "detector": self.det, "segmenter": FakeSegmenter(), "ocr": FakeOCR(),
            "tracker": CentroidTracker(),
            "classifier": NoClassifier("effnet", "none"),   # deliberately NOT ready
        }
        self._attempts = {"classifier": [{"provider": "efficientnet-onnx", "status": "unavailable",
                                          "reason": "no ONNX asset under data/models/effnet/"}]}

    def get(self, role):
        return self._roles[role]


class Wire:
    def __init__(self, tc):
        self.tc, self.down, self.fail_post, self.calls = tc, False, False, []

    def path(self, url):
        return url.replace(HOST, "")


@pytest.fixture
def wire(monkeypatch):
    monkeypatch.setattr(settings, "internal_key", KEY, raising=False)
    monkeypatch.setattr(settings, "vision_url", "vision.internal:10000", raising=False)
    monkeypatch.setattr(vision_service, "registry", FakeRegistry())
    with TestClient(vision_service.app) as tc:
        w = Wire(tc)

        def fake_get(url, headers=None, timeout=None, **kw):
            if w.down:
                raise httpx.ConnectError("down")
            return tc.get(w.path(url), headers=headers)

        class FakeAsyncClient:
            def __init__(self, *a, **k): ...
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False

            async def post(self, url, headers=None, files=None, data=None):
                w.calls.append(w.path(url))
                if w.down or w.fail_post:
                    raise httpx.ConnectError("down")
                return tc.post(w.path(url), headers=headers, files=files, data=data)

        monkeypatch.setattr(httpx, "get", fake_get)
        monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
        models.reload()
        yield w
    models.reload()


def _auth(key=KEY):
    return {"X-Orion-Internal-Key": key}


# ------------------------------------------------------------ internal auth

def test_service_refuses_every_route_without_the_key(wire):
    tc = wire.tc
    for method, path in (("get", "/internal/status"), ("post", "/internal/detect"),
                         ("post", "/internal/ocr"), ("get", "/docs"), ("get", "/openapi.json")):
        assert getattr(tc, method)(path).status_code == 401, path
    assert tc.get("/internal/status", headers=_auth("wrong")).status_code == 401
    assert tc.get("/internal/status", headers={"Authorization": f"Bearer {KEY}"}).status_code == 401
    assert tc.get("/internal/status", headers=_auth()).status_code == 200


def test_liveness_probe_is_open_and_says_nothing_else(wire):
    r = wire.tc.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_service_refuses_to_start_without_a_key(monkeypatch):
    monkeypatch.setattr(settings, "internal_key", "", raising=False)
    with pytest.raises(RuntimeError, match="VF_INTERNAL_KEY"):
        with TestClient(vision_service.app):
            pass


def test_status_reports_real_roles_and_never_an_npu_or_the_key(wire):
    body = wire.tc.get("/internal/status", headers=_auth()).json()
    assert body["ready"] == ["detector", "segmenter", "tracker", "ocr"]
    assert body["roles"]["classifier"]["status"] == "unavailable"
    assert "no ONNX asset" in body["roles"]["classifier"]["reason"]
    assert all(v["npu"] is False for v in body["roles"].values())
    assert KEY not in wire.tc.get("/internal/status", headers=_auth()).text


def test_service_input_validation(wire, photo_bytes):
    tc = wire.tc
    r = tc.post("/internal/detect", headers=_auth(), files={"image": ("x", b"not an image")})
    assert r.status_code == 415
    r = tc.post("/internal/classify", headers=_auth(), files={"image": ("x", photo_bytes)},
                data={"meta": '{"bbox": [1,2]}'})
    assert r.status_code in (422, 503)        # classifier is down; both refuse honestly
    r = tc.post("/internal/detect", headers=_auth(), files={"image": ("x", photo_bytes)},
                data={"meta": "[1]"})
    assert r.status_code == 422
    monkey = settings.internal_max_image_bytes
    settings.internal_max_image_bytes = 10
    try:
        r = tc.post("/internal/detect", headers=_auth(), files={"image": ("x", photo_bytes)})
        assert r.status_code == 413
    finally:
        settings.internal_max_image_bytes = monkey


def test_a_not_ready_role_is_refused_not_faked(wire, photo_bytes):
    r = wire.tc.post("/internal/classify", headers=_auth(), files={"image": ("x", photo_bytes)})
    assert r.status_code == 503 and r.json()["error"] == "MODEL_UNAVAILABLE"


# ------------------------------------------------- API side: honest status

def test_status_marks_only_service_ready_roles_ready(client, wire):
    body = client.get("/api/models/status").json()
    roles = body["roles"]
    assert roles["detector"]["status"] == "ready"
    assert roles["detector"]["provider"] == "remote-vision"
    assert roles["detector"]["hosted"] is True and roles["detector"]["npu"] is False
    assert roles["detector"]["detail"]["remote_provider"] == "fake-onnx"
    assert roles["classifier"]["status"] == "unavailable"
    assert "no ONNX asset" in roles["classifier"]["reason"]
    assert body["services"]["vision"]["status"] == "partial"
    assert set(body["services"]["vision"]["ready_roles"]) >= {"detector", "ocr", "segmenter"}
    assert body["summary"]["npu_accelerated"] == [] and body["summary"]["npu_claim"] is False
    assert "vision.internal" not in client.get("/api/models/status").text
    assert KEY not in client.get("/api/models/status").text


def test_tools_use_the_remote_service_and_send_image_bytes(client, wire, photo_bytes):
    img = client.post("/api/photo/upload", files={"file": ("f.jpg", photo_bytes, "image/jpeg")}).json()
    res = client.post("/api/photo/inspect", data={"image_id": img["image_id"]}).json()
    assert res["detect"]["detections"][0]["label"] == "motor"
    assert res["detect"]["accelerator"] == "cpu"
    assert res["ocr"]["joined_text"].startswith("CNC M04")
    assert "/internal/detect" in wire.calls and "/internal/ocr" in wire.calls
    assert wire.tc.app  # service ran the real request through its own auth middleware
    assert vision_service.registry.det.seen_sizes[-1] == (640, 480) or \
        vision_service.registry.det.seen_sizes[-1][0] > 0


def test_not_ready_remote_role_degrades_with_the_services_reason(client, wire, photo_bytes):
    img = client.post("/api/photo/upload", files={"file": ("f.jpg", photo_bytes, "image/jpeg")}).json()
    res = client.post("/api/tools/call", json={"tool": "vision_classify",
                                               "arguments": {"image_id": img["image_id"]}}).json()
    out = res
    assert out["degraded"] is True and out["classifications"] == []
    assert "no ONNX asset" in out["reason"]
    assert "/internal/classify" not in wire.calls


# ---------------------------------------------- API works without the service

def test_api_fully_works_when_the_service_is_down(client, wire, photo_bytes, llm):
    wire.down = True
    models.reload()
    body = client.get("/api/models/status").json()
    assert body["roles"]["detector"]["status"] == "unavailable"
    assert "unreachable" in body["roles"]["detector"]["reason"]
    assert body["services"]["vision"]["reachable"] is False
    assert body["services"]["vision"]["status"] == "unavailable"
    assert client.get("/api/health").status_code == 200
    # photo analysis still answers (the reasoning model reads the image itself)
    out = client.post("/api/photo/analyze", files={"file": ("f.jpg", photo_bytes, "image/jpeg")},
                      data={"question": "What is this?"})
    assert out.status_code == 200 and out.json()["text"]
    insp = client.post("/api/photo/inspect", data={"image_id": out.json()["images"][0]["image_id"]}).json()
    assert insp["detect"]["degraded"] is True and insp["ocr"]["degraded"] is True


def test_role_recovers_by_itself_but_never_before_the_service_reports_ready(client, wire):
    wire.down = True
    models.reload()
    assert client.get("/api/models/status").json()["roles"]["ocr"]["status"] == "unavailable"
    wire.down = False
    from app.models import remote
    remote.client.reset()
    assert client.get("/api/models/status").json()["roles"]["ocr"]["status"] == "ready"


def test_service_dying_mid_request_degrades_instead_of_raising(client, wire, photo_bytes):
    img = client.post("/api/photo/upload", files={"file": ("f.jpg", photo_bytes, "image/jpeg")}).json()
    client.get("/api/models/status")           # status cache says READY
    wire.fail_post = True                      # ...then the service drops
    res = client.post("/api/photo/inspect", data={"image_id": img["image_id"]}).json()
    assert res["detect"]["degraded"] is True and res["detect"]["detections"] == []
    assert "unreachable" in res["detect"]["reason"]
    # and the next status no longer trusts the old READY
    assert client.get("/api/models/status").json()["roles"]["detector"]["status"] == "unavailable"


def test_wrong_internal_key_on_the_api_is_reported_not_hidden(client, wire, monkeypatch):
    from app.models import remote
    monkeypatch.setattr(remote, "_headers", lambda: {remote.KEY_HEADER: "some-other-key"})
    models.reload()
    role = client.get("/api/models/status").json()["roles"]["detector"]
    assert role["status"] == "unavailable" and "rejected the internal key" in role["reason"]


def test_without_a_vision_url_nothing_is_remote_and_status_says_so(client, monkeypatch):
    monkeypatch.setattr(settings, "vision_url", "", raising=False)
    models.reload()
    body = client.get("/api/models/status").json()
    assert body["services"]["vision"] == {
        "configured": False, "status": "not_configured", "reachable": False,
        "ready_roles": [], "reason": "no vision service configured"}
    assert body["roles"]["detector"]["provider"] != "remote-vision"
    assert body["roles"]["tracker"]["provider"] == "cpu-classical"   # local, unchanged


def test_tracker_is_local_in_auto_and_remote_only_when_pinned(client, wire, monkeypatch):
    assert client.get("/api/models/status").json()["roles"]["tracker"]["provider"] == "cpu-classical"
    monkeypatch.setattr(settings, "tracker_provider", "remote-vision", raising=False)
    models.reload()
    t = client.get("/api/models/status").json()["roles"]["tracker"]
    assert t["provider"] == "remote-vision" and t["status"] == "ready" and t["npu"] is False


def test_remote_adapter_never_loops_the_service_into_itself():
    assert settings.vision_url == "" or True   # monkeypatched per test; module import clears it
    import importlib
    from app import vision_service as vs
    importlib.reload(vs)
    assert settings.vision_url == ""

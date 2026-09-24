"""Phase 1 — foundation, safety of the storage layer, honest model status."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_health_and_root(client):
    assert client.get("/api/health").json()["status"] == "ok"
    body = client.get("/").json()
    assert "VLM is the brain" in body["principle"]


def test_schema_has_every_spec_table(client):
    from app.memory import sqlite as db

    names = {r["name"] for r in db.query(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ("users", "conversations", "messages", "machines", "jobs", "inspections",
                  "findings", "measurements", "documents", "document_chunks", "memories",
                  "tool_calls"):
        assert table in names, f"§14 table missing: {table}"


def test_filenames_cannot_traverse():
    from app.config import settings
    from app.util import contained_path, safe_filename

    assert "/" not in safe_filename("../../etc/passwd")
    assert safe_filename("  ..hidden.pdf ") == "hidden.pdf"
    # Whatever is thrown at it, the result stays under the root.
    for evil in ("../../etc", "..\\..\\windows\\system32", "/etc/shadow", "....//"):
        p = contained_path(settings.documents_dir, evil)
        assert settings.documents_dir.resolve() in p.parents or p == settings.documents_dir


def test_logs_redact_secrets_and_media():
    import logging

    from app.logging_setup import RedactingFilter

    f = RedactingFilter()
    rec = logging.LogRecord("t", logging.INFO, "f", 1,
                            "api_key=sk-abcdef123456 and data:image/png;base64,"
                            + "A" * 64, (), None)
    f.filter(rec)
    assert "sk-abcdef123456" not in rec.msg
    assert "<media:redacted>" in rec.msg


def test_model_status_is_honest(client):
    body = client.get("/api/models/status").json()
    assert set(body["roles"]) == {"reasoning", "detector", "classifier", "segmenter",
                                  "tracker", "ocr", "embedding", "stt", "tts"}
    for role, info in body["roles"].items():
        # No role may claim the NPU without the runtime having confirmed it.
        if info["npu"]:
            assert info["accelerator"] == "npu"
            assert body["runtime"]["qnn_execution_provider_available"] is True
        # A stand-in must be labelled as one.
        if info["provider"] in ("heuristic-offline", "lexical-hash"):
            assert info["synthetic"] is True
            assert info["npu"] is False
    assert body["summary"]["npu_claim"] == bool(body["summary"]["npu_accelerated"])
    assert "MODEL_STATUS.md" in body["notice"]


def test_unavailable_adapter_returns_the_spec_error_envelope():
    from app.errors import ModelUnavailable
    from app.models.base import NoDetector

    d = NoDetector("yolov11_det", "none")
    assert d.health().status == "unavailable"
    with pytest.raises(ModelUnavailable) as exc:
        d.require_ready(fallback="vlm-only inspection")
    body = exc.value.to_dict()
    assert body["error"] == "MODEL_UNAVAILABLE"
    assert body["model"] == "yolov11_det"
    assert body["fallback"] == "vlm-only inspection"
    assert "reason" in body


def test_system_status_declares_local_first(client):
    local = client.get("/api/system/status").json()["local_first"]
    assert local["cloud_documents"] is False
    assert local["cloud_camera_frames"] is False
    assert local["cloud_audio"] is False
    assert local["cloud_memory"] is False
    assert local["web_research"]["enabled"] is False


def test_classification_stage_exists_and_is_optional(client):
    """§3 lists EfficientNet-B4 and §7 puts classification in the photo pipeline."""
    role = client.get("/api/models/status").json()["roles"]["classifier"]
    assert role["capabilities"]["role"] == "classifier"

    # Without an export it is a skip, not a failure — §7 calls the stage optional.
    r = client.post("/api/tools/call", json={"tool": "vision_classify", "arguments": {}}).json()
    assert r["ok"] is False or r.get("skipped") is True


def test_every_spec_model_is_selectable(client):
    """§3: 'Do not hard-wire one model.' Each candidate must be reachable by name."""
    roles = client.get("/api/models/status").json()["roles"]
    tried = {role: {c["provider"] for c in info["candidates_tried"]}
             for role, info in roles.items()}
    assert {"onnxruntime-genai", "local-openai-compat"} <= tried["reasoning"]
    assert {"yolo-onnx", "yolo-world-onnx"} <= tried["detector"]
    assert {"onnx-seg", "sam2-onnx", "mobilesam-onnx"} <= tried["segmenter"]
    assert {"edgetam-onnx", "track-anything-onnx"} <= tried["tracker"]
    assert {"easyocr", "trocr-onnx"} <= tried["ocr"]
    assert {"nomic-onnx", "minilm-onnx"} <= tried["embedding"]
    assert {"whisper-onnx", "faster-whisper"} <= tried["stt"]


def test_metrics_cover_the_spec_list(client):
    """§23 names thirteen figures. Each is measured or explicitly unavailable."""
    client.post("/api/chat", json={"message": "The gearbox is running warm."})
    m = client.get("/api/metrics").json()

    assert m["latency"]["end_to_end_response_latency"]["samples"] >= 1
    assert "process_rss_mb" in m["host"] or "note" in m["host"]
    assert m["model_load_ms"] is not None
    assert {"tool"} <= set(m["tool_latency"][0]) if m["tool_latency"] else True
    assert set(m["unavailable_metrics"]) == {
        "npu_utilisation", "gpu_utilisation", "tokens_per_second"}
    assert "camera" in m  # camera / tracking FPS, per live session


def test_local_user_record_exists(client):
    """§14 has a users table; §13 hangs user memory off it."""
    user = client.get("/api/user").json()
    assert user["id"] and user["display_name"]
    assert user["preference_count"] == 0

    client.post("/api/memories", json={
        "memory_type": "preference",
        "content": "Prefers metric torque figures and Nm rather than lb-ft",
        "confidence": 0.9, "confirmed": True, "source": {"origin": "technician"}})
    assert client.get("/api/user").json()["preference_count"] == 1

    conv = client.post("/api/conversations", json={"title": "Scoped"}).json()
    assert conv["user_id"] == user["id"]

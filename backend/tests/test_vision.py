"""Phases 3 and 6 — photo mode, live-mode scheduling, and graceful degradation."""

from __future__ import annotations


def test_photo_analyze_stores_the_image_and_answers(client, photo_bytes):
    body = client.post("/api/photo/analyze", files={
        "file": ("frame.jpg", photo_bytes, "image/jpeg")},
        data={"question": "What am I looking at and what should I check?"}).json()

    assert body["images"][0]["width"] == 640
    assert body["text"]
    # With no detector or OCR present the answer must say so, not invent content.
    assert "vision_detect" in {s["tool"] for s in body["work_trail"]}
    assert "vision_detect" in body["degraded_tools"] or body["confidence"] is not None


def test_degraded_detector_names_its_fallback(client, photo_bytes):
    img = client.post("/api/photo/upload", files={
        "file": ("frame.jpg", photo_bytes, "image/jpeg")}).json()
    res = client.post("/api/photo/inspect", data={"image_id": img["image_id"]}).json()

    assert res["detect"]["ok"] is True
    assert res["detect"]["degraded"] is True
    assert res["detect"]["fallback"]           # §25 names what takes over
    assert res["detect"]["image"]["width"] == 640
    assert res["ocr"]["degraded"] is True


def test_non_image_upload_is_rejected(client):
    r = client.post("/api/photo/upload", files={
        "file": ("not-an-image.jpg", b"this is plain text, not a JPEG", "image/jpeg")})
    assert r.status_code == 415


def test_live_session_lifecycle_and_rate_limiting(client, photo_bytes, second_frame):
    start = client.post("/api/live/start", json={}).json()
    sid = start["session_id"]
    assert start["policy"]["vlm_min_gap_ms"] > 0

    # Frame 1: a brand-new scene, so the reasoning model is allowed to wake.
    f1 = client.post("/api/live/frame", files={
        "file": ("f1.jpg", photo_bytes, "image/jpeg")}, data={"session_id": sid}).json()
    assert f1["frame_index"] == 1
    assert f1["ran"]["detector"] is True

    # Frame 2: the identical scene immediately after — nothing meaningful changed,
    # so §8 says the VLM must not run.
    f2 = client.post("/api/live/frame", files={
        "file": ("f2.jpg", photo_bytes, "image/jpeg")}, data={"session_id": sid}).json()
    assert f2["ran"]["reasoning"] is False
    assert f2["scene_change"] < 0.05

    # A direct question always wakes it, regardless of the rate limit.
    f3 = client.post("/api/live/frame", files={
        "file": ("f3.jpg", second_frame, "image/jpeg")},
        data={"session_id": sid, "question": "What changed?"}).json()
    assert f3["ran"]["reasoning"] is True
    assert "the technician asked a question" in f3["vlm"]["reasons"]
    assert f3["scene_change"] > 0.1

    stopped = client.post("/api/live/stop", data={"session_id": sid}).json()
    assert stopped["status"] == "stopped"
    assert stopped["frames_seen"] == 3
    assert stopped["vlm_calls"] <= 2, "the VLM ran more often than events justified"


def test_frame_for_an_unknown_session_is_rejected(client, photo_bytes):
    r = client.post("/api/live/frame", files={
        "file": ("f.jpg", photo_bytes, "image/jpeg")},
        data={"session_id": "live_doesnotexist"})
    assert r.status_code == 404


def test_expired_session_reports_itself_as_expired(client, photo_bytes, monkeypatch):
    from app.agent.live_session import sessions
    from app.config import settings

    sid = client.post("/api/live/start", json={}).json()["session_id"]
    monkeypatch.setattr(settings, "live_session_ttl_s", 0, raising=False)
    r = client.post("/api/live/frame", files={
        "file": ("f.jpg", photo_bytes, "image/jpeg")}, data={"session_id": sid})
    assert r.status_code == 410


def test_scene_change_triggers_ocr_and_detector(client, photo_bytes, second_frame):
    sid = client.post("/api/live/start", json={}).json()["session_id"]
    client.post("/api/live/frame", files={"file": ("a.jpg", photo_bytes, "image/jpeg")},
                data={"session_id": sid})
    f = client.post("/api/live/frame", files={"file": ("b.jpg", second_frame, "image/jpeg")},
                    data={"session_id": sid}).json()
    assert f["ran"]["detector"] is True
    assert f["ran"]["ocr"] is True


def test_tracker_is_classical_and_says_so(client):
    body = client.get("/api/models/status").json()["roles"]["tracker"]
    if body["status"] == "ready":
        assert body["npu"] is False
        assert body["accelerator"] == "cpu"
        assert "not a learned tracker" in body["detail"]["note"].lower()


def test_voice_degrades_without_claiming_cloud(client):
    t = client.post("/api/voice/transcribe", files={
        "file": ("clip.wav", b"RIFF0000WAVEfmt ", "audio/wav")}).json()
    assert t["degraded"] is True
    assert t["text"] == ""
    assert "fallback" in t

    s = client.post("/api/voice/synthesize", json={"text": "Isolate before testing."}).json()
    assert s["degraded"] is True
    assert s["text"] == "Isolate before testing."


def test_scene_signature_tracks_the_subject_not_the_lighting():
    """§8's scene-change trigger has to survive a handheld camera.

    A raw grayscale grid does not: two different dark scenes score nearly
    identical and the detector never wakes, while an auto-exposure shift on a
    stationary camera looks like a whole new scene.
    """
    import io
    import tempfile
    from pathlib import Path

    from PIL import Image, ImageEnhance

    from app.config import settings
    from app.models._imaging import scene_signature, signature_distance
    from app.models.base import ImageRef
    from tests import fixtures

    tmp = Path(tempfile.mkdtemp())

    def sig(data_or_img, name):
        path = tmp / f"{name}.jpg"
        img = (Image.open(io.BytesIO(data_or_img)) if isinstance(data_or_img, bytes)
               else data_or_img)
        img.convert("RGB").save(path, quality=92)
        return scene_signature(ImageRef(id=name, path=str(path)))

    threshold = settings.live_scene_change_threshold
    base_img = Image.open(io.BytesIO(fixtures.control_panel()))
    base = sig(fixtures.control_panel(), "base")

    assert signature_distance(base, base) == 0.0

    # The camera moved or the exposure drifted — same scene, must not trigger.
    quiet = {
        "4px shift": base_img.transform(base_img.size, Image.AFFINE, (1, 0, 4, 0, 1, 3)),
        "exposure +30%": ImageEnhance.Brightness(base_img).enhance(1.3),
        "exposure -35%": ImageEnhance.Brightness(base_img).enhance(0.65),
        "contrast +40%": ImageEnhance.Contrast(base_img).enhance(1.4),
    }
    for name, img in quiet.items():
        d = signature_distance(base, sig(img, name.replace(" ", "_").replace("%", "")))
        assert d < threshold, f"{name} scored {d}, would have been read as a new scene"

    # The technician panned to something else — must trigger.
    for name in ("motor_assembly", "pcb_with_labels", "motor_nameplate"):
        d = signature_distance(base, sig(getattr(fixtures, name)(), name))
        assert d >= threshold, f"panning to {name} scored only {d}, below {threshold}"

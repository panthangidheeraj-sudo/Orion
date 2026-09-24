"""Live mode (§8): /api/live/start, /api/live/frame, /api/live/stop.

The transport is plain HTTP for V1; §20 notes it can become WebSocket or
WebRTC later without the agent changing, because the scheduling decisions all
live in app/agent/live_session.py rather than in the transport.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, UploadFile

from app.agent.live_session import sessions
from app.agent.orchestrator import orchestrator
from app.agent.tool_registry import registry as tool_registry
from app.api._media import read_upload, store_image
from app.config import settings
from app.logging_setup import get_logger
from app.memory import memory_service as M
from app.models.registry import registry as models
from app.schemas.vision import LiveStartRequest
from app.tools.vision_tools import resolve_image
from app.util import timed

log = get_logger(__name__)
router = APIRouter(prefix="/api/live", tags=["live"])

LIVE_QUESTION = ("Look at what the camera is showing now and tell me what changed and what "
                 "to do next. Be brief.")


@router.post("/start")
async def start(req: LiveStartRequest) -> Dict[str, Any]:
    conversation = M.ensure_conversation(req.conversation_id, title="Live inspection")
    inspection_id = req.inspection_id
    if inspection_id is None and req.job_id:
        inspection_id = M.start_inspection(req.job_id, "live")["id"]
    state = sessions.start(conversation["id"], inspection_id, req.job_id, req.target_label)
    return {**state.public(),
            "policy": {
                "detect_interval_ms": settings.live_detect_interval_ms,
                "ocr_interval_ms": settings.live_ocr_interval_ms,
                "vlm_min_gap_ms": settings.live_vlm_min_gap_ms,
                "scene_change_threshold": settings.live_scene_change_threshold,
                "note": "The reasoning model runs on meaningful events only, never per frame.",
            }}


@router.post("/frame")
async def frame(session_id: str = Form(...),
                file: UploadFile = File(...),
                question: Optional[str] = Form(None),
                deep: bool = Form(False),
                target_label: Optional[str] = Form(None),
                keep: bool = Form(False)) -> Dict[str, Any]:
    state = sessions.get(session_id)
    state.last_seen = time.time()
    state.frames_seen += 1
    if target_label:
        state.target_label = target_label

    data = await read_upload(file, limit=25 * 1024 * 1024)
    stored = store_image(data, source="live_frame", conversation_id=state.conversation_id,
                         inspection_id=state.inspection_id)
    ref = resolve_image(stored["image_id"])

    timings: Dict[str, float] = {}
    with timed() as t_plan:
        plan = sessions.plan(state, ref, question, deep)
    timings["plan"] = t_plan["ms"]

    ctx = {"image_ids": [stored["image_id"]], "conversation_id": state.conversation_id,
           "inspection_id": state.inspection_id, "job_id": state.job_id,
           "track_state": state.track_state, "detections": state.detections}

    if plan["run_detector"]:
        with timed() as t:
            res = await tool_registry.call("vision_detect",
                                           {"image_id": stored["image_id"]}, context=ctx)
        timings["detect"] = t["ms"]
        if res.get("ok"):
            state.detections = res.get("detections") or []
            state.detector_runs += 1
            state.last_detect_ms = plan["now_ms"]
    ctx["detections"] = state.detections

    track: Optional[Dict[str, Any]] = None
    if state.detections:
        with timed() as t:
            track = await tool_registry.call(
                "vision_track",
                {"image_id": stored["image_id"], "target_label": state.target_label},
                context=ctx)
        timings["track"] = t["ms"]
        state.tracker_runs += 1
        if track.get("ok") and track.get("target"):
            state.track_state = {"target": track["target"],
                                 "track_id": track["target"].get("track_id")}

    if plan["run_ocr"]:
        with timed() as t:
            res = await tool_registry.call("ocr_extract",
                                           {"image_id": stored["image_id"]}, context=ctx)
        timings["ocr"] = t["ms"]
        if res.get("ok"):
            state.text_regions = res.get("text_regions") or []
            state.ocr_runs += 1
            state.last_ocr_ms = plan["now_ms"]

    triggers = sessions.vlm_triggers(state, plan, state.detections, state.text_regions,
                                     question, deep)

    analysis = None
    if triggers["should_call_vlm"]:
        with timed() as t:
            analysis = await orchestrator.ask(
                question or LIVE_QUESTION,
                conversation_id=state.conversation_id,
                image_ids=[stored["image_id"]],
                job_id=state.job_id, inspection_id=state.inspection_id,
                mode="live", persist=bool(question))
        timings["reasoning"] = t["ms"]
        state.vlm_calls += 1
        state.last_vlm_ms = time.time() * 1000.0
        for r in state.text_regions:
            state.seen_text.add((r.get("text") or "").strip().upper())

    if not keep and not triggers["should_call_vlm"]:
        # Frames that changed nothing are not worth keeping on disk.
        _discard(stored["image_id"])

    return {
        "session_id": session_id,
        "frame_index": state.frames_seen,
        "detections": state.detections,
        "text_regions": state.text_regions,
        "track": (track or {}).get("target") if track else None,
        "scene_change": plan["scene_change"],
        "ran": {"detector": plan["run_detector"], "ocr": plan["run_ocr"],
                "tracker": bool(state.detections), "reasoning": bool(analysis)},
        "vlm": triggers,
        "analysis": analysis,
        "timings_ms": {k: round(v, 2) for k, v in timings.items()},
        "session": state.public(),
    }


@router.post("/stop")
async def stop(session_id: str = Form(...), summary: Optional[str] = Form(None)) -> Dict[str, Any]:
    result = sessions.stop(session_id, reason="stopped")
    if result.get("inspection_id"):
        try:
            M.end_inspection(result["inspection_id"], summary)
        except Exception:
            pass
    return result


@router.get("/sessions")
async def active_sessions() -> Dict[str, Any]:
    sessions.sweep()
    active = sessions.active()
    return {"sessions": active, "count": len(active)}


def _discard(image_id: str) -> None:
    from pathlib import Path

    from app.memory import sqlite as db

    row = db.query_one("SELECT path FROM images WHERE id = ?", (image_id,))
    if row:
        try:
            Path(row["path"]).unlink(missing_ok=True)
        except OSError:
            pass
        db.execute("DELETE FROM images WHERE id = ?", (image_id,))

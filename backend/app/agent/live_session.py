"""Live mode session state (§8).

The rule this file exists to enforce: **do not run a heavy VLM 30 times a
second.**  Each frame is cheap — a 12x12 grayscale fingerprint — and the
expensive senses are rate-limited independently:

* the detector runs on an interval;
* the tracker runs every frame it has detections for, because it is classical
  and costs almost nothing;
* OCR runs on a slower interval, or when the scene changed;
* the VLM runs only on a *meaningful event*, and never twice inside the
  minimum gap.

The triggers are exactly the ones §8 lists: the user asks, the selected object
changes, the scene changes significantly, OCR finds important text or an error
code, a confidence/anomaly threshold fires, or deep inspection is requested.
Every decision is returned to the caller, so the reason the VLM did or did not
wake is visible rather than mysterious — which is also what makes the
Snapdragon efficiency story demonstrable (§23).
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.config import settings
from app.errors import NotFound, SessionExpired
from app.logging_setup import get_logger
from app.memory import sqlite as db
from app.models._imaging import scene_signature, signature_distance
from app.models.base import ImageRef
from app.util import new_id, utc_now

log = get_logger(__name__)

# Text worth waking the reasoning model for: E17, F-024, ALARM, ERR 5, TRIP.
IMPORTANT_TEXT = re.compile(
    r"\b([A-Z]{1,3}[-\s]?\d{1,4}|ERR(?:OR)?|ALARM|FAULT|TRIP|OVERLOAD|WARNING|DANGER|"
    r"HIGH\s?VOLTAGE|LOCK\s?OUT)\b")


@dataclass
class LiveState:
    id: str
    conversation_id: str
    inspection_id: Optional[str] = None
    job_id: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    frames_seen: int = 0
    vlm_calls: int = 0
    detector_runs: int = 0
    ocr_runs: int = 0
    tracker_runs: int = 0
    last_detect_ms: float = 0.0
    last_ocr_ms: float = 0.0
    last_vlm_ms: float = 0.0
    last_signature: List[float] = field(default_factory=list)
    detections: List[Dict[str, Any]] = field(default_factory=list)
    text_regions: List[Dict[str, Any]] = field(default_factory=list)
    track_state: Dict[str, Any] = field(default_factory=dict)
    target_label: Optional[str] = None
    seen_text: set = field(default_factory=set)
    status: str = "active"

    def public(self) -> Dict[str, Any]:
        uptime = max(1e-6, time.time() - self.started_at)
        return {
            "session_id": self.id,
            "conversation_id": self.conversation_id,
            "inspection_id": self.inspection_id,
            "job_id": self.job_id,
            "status": self.status,
            "frames_seen": self.frames_seen,
            "vlm_calls": self.vlm_calls,
            "detector_runs": self.detector_runs,
            "ocr_runs": self.ocr_runs,
            "target": self.track_state.get("target"),
            "uptime_s": round(uptime, 1),
            # §23 asks for camera and tracking FPS. These are measured over the
            # session's own lifetime, not assumed from a target frame rate.
            "camera_fps": round(self.frames_seen / max(1e-6, uptime), 2),
            "tracking_fps": round(self.tracker_runs / max(1e-6, uptime), 2),
            "detector_fps": round(self.detector_runs / max(1e-6, uptime), 2),
            "vlm_calls_per_minute": round(self.vlm_calls / max(1e-6, uptime / 60.0), 2),
            "frames_per_vlm_call": round(self.frames_seen / self.vlm_calls, 1)
            if self.vlm_calls else None,
        }


class LiveSessions:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: Dict[str, LiveState] = {}

    def start(self, conversation_id: str, inspection_id: Optional[str] = None,
              job_id: Optional[str] = None, target_label: Optional[str] = None) -> LiveState:
        self.sweep()
        state = LiveState(id=new_id("live"), conversation_id=conversation_id,
                          inspection_id=inspection_id, job_id=job_id,
                          target_label=target_label)
        with self._lock:
            self._sessions[state.id] = state
        db.insert("live_sessions", {
            "id": state.id, "conversation_id": conversation_id,
            "inspection_id": inspection_id, "status": "active",
            "started_at": utc_now(), "ended_at": None, "frames_seen": 0,
            "vlm_calls": 0, "state_json": json.dumps({"target_label": target_label}),
        })
        log.info("live session %s started", state.id)
        return state

    def get(self, session_id: str) -> LiveState:
        with self._lock:
            state = self._sessions.get(session_id)
        if state is None:
            if db.query_one("SELECT id FROM live_sessions WHERE id = ?", (session_id,)):
                raise SessionExpired("that live session has ended", session_id=session_id)
            raise NotFound("no such live session", session_id=session_id)
        if time.time() - state.last_seen > settings.live_session_ttl_s:
            self.stop(session_id, reason="timed out")
            raise SessionExpired("that live session timed out", session_id=session_id)
        return state

    def stop(self, session_id: str, reason: str = "stopped") -> Dict[str, Any]:
        with self._lock:
            state = self._sessions.pop(session_id, None)
        db.execute(
            "UPDATE live_sessions SET status = ?, ended_at = ?, frames_seen = ?, vlm_calls = ?"
            " WHERE id = ?",
            (reason, utc_now(), state.frames_seen if state else 0,
             state.vlm_calls if state else 0, session_id))
        if state is None:
            return {"session_id": session_id, "status": reason, "known": False}
        state.status = reason
        log.info("live session %s %s after %d frame(s), %d VLM call(s)",
                 session_id, reason, state.frames_seen, state.vlm_calls)
        return {**state.public(), "status": reason, "known": True}

    def sweep(self) -> int:
        now = time.time()
        with self._lock:
            stale = [sid for sid, s in self._sessions.items()
                     if now - s.last_seen > settings.live_session_ttl_s]
        for sid in stale:
            self.stop(sid, reason="timed out")
        return len(stale)

    def active(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [s.public() for s in self._sessions.values()]

    # -------------------------------------------------------------- scheduling
    def plan(self, state: LiveState, frame: ImageRef, user_question: Optional[str],
             deep: bool) -> Dict[str, Any]:
        """Decide what runs on this frame, and say why."""
        now_ms = time.time() * 1000.0
        signature = scene_signature(frame)
        change = signature_distance(state.last_signature, signature) if state.last_signature else 1.0
        state.last_signature = signature

        run_detector = (now_ms - state.last_detect_ms) >= settings.live_detect_interval_ms \
            or change >= settings.live_scene_change_threshold
        run_ocr = (now_ms - state.last_ocr_ms) >= settings.live_ocr_interval_ms \
            or change >= settings.live_scene_change_threshold

        return {
            "scene_change": round(change, 4),
            "run_detector": bool(run_detector),
            "run_ocr": bool(run_ocr),
            "run_tracker": True,
            "now_ms": now_ms,
        }

    def vlm_triggers(self, state: LiveState, plan: Dict[str, Any],
                     detections: List[Dict[str, Any]], text_regions: List[Dict[str, Any]],
                     user_question: Optional[str], deep: bool) -> Dict[str, Any]:
        """The §8 trigger list, evaluated explicitly."""
        reasons: List[str] = []
        if user_question:
            reasons.append("the technician asked a question")
        if deep:
            reasons.append("deep inspection requested")

        target = (state.track_state.get("target") or {}).get("label")
        top = detections[0]["label"] if detections else None
        if top and target and top != target:
            reasons.append(f"selected object changed: {target} → {top}")
        elif top and not state.detections:
            reasons.append(f"first object acquired: {top}")

        if plan["scene_change"] >= settings.live_scene_change_threshold:
            reasons.append(f"scene changed ({plan['scene_change']:.2f})")

        new_text = []
        for r in text_regions:
            t = (r.get("text") or "").strip().upper()
            if t and t not in state.seen_text and IMPORTANT_TEXT.search(t):
                new_text.append(t)
        if new_text:
            reasons.append("important text read: " + ", ".join(new_text[:3]))

        low_conf = [d for d in detections if 0.30 <= d.get("confidence", 1.0) < 0.45]
        if len(low_conf) >= 3:
            reasons.append("several low-confidence detections — the scene is ambiguous")

        gap_ok = (plan["now_ms"] - state.last_vlm_ms) >= settings.live_vlm_min_gap_ms
        forced = bool(user_question or deep)
        should = bool(reasons) and (gap_ok or forced)

        return {
            "should_call_vlm": should,
            "reasons": reasons,
            "suppressed_by_rate_limit": bool(reasons) and not gap_ok and not forced,
            "ms_since_last_vlm": round(plan["now_ms"] - state.last_vlm_ms, 1)
            if state.last_vlm_ms else None,
            "new_important_text": new_text,
        }


sessions = LiveSessions()

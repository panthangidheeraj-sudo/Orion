"""System and model status (§20, §23, §4).

``/api/models/status`` is the honesty endpoint: it reports what loaded, on
which accelerator, and which roles are running deterministic stand-ins rather
than neural models.  A demo can be held against it.
"""

from __future__ import annotations

import os
import platform
import time
from typing import Any, Dict

from fastapi import APIRouter

from app.agent.live_session import sessions
from app.agent.tool_registry import registry as tool_registry
from app.config import settings
from app.knowledge import web_search as ws
from app.logging_setup import get_logger
from app.memory import sqlite as db
from app.memory import vector_store as vs
from app.metrics import collector
from app.models.registry import registry as models

log = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["system"])
STARTED_AT = time.time()


@router.get("/system/status")
async def system_status() -> Dict[str, Any]:
    counts = {}
    for table in ("conversations", "messages", "documents", "document_chunks", "machines",
                  "jobs", "inspections", "findings", "measurements", "memories",
                  "images", "reports", "tool_calls"):
        row = db.query_one(f"SELECT COUNT(*) AS n FROM {table}")
        counts[table] = (row or {}).get("n", 0)

    return {
        "status": "ok",
        "app": "VisionField Copilot backend",
        "version": "1.0.0",
        "uptime_s": round(time.time() - STARTED_AT, 1),
        "local_first": {
            "cloud_documents": False,
            "cloud_camera_frames": False,
            "cloud_audio": False,
            "cloud_memory": False,
            "web_research": ws.get_provider().status(),
            "note": "Nothing leaves this machine unless web research is explicitly "
                    "enabled, and then only the search query (§24).",
        },
        "storage": {
            "data_dir": str(settings.data_dir),
            "database": str(settings.db_path),
            "counts": counts,
            "vector_store": vs.backend_info(),
        },
        "live_sessions": sessions.active(),
        "tools": {"count": len(tool_registry.names()), "names": tool_registry.names()},
        "host": {
            "system": platform.system(), "release": platform.release(),
            "machine": platform.machine(), "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
        },
    }


@router.get("/models/status")
async def models_status() -> Dict[str, Any]:
    return models.status()


@router.post("/models/reload")
async def models_reload() -> Dict[str, Any]:
    """Re-probe every adapter after dropping a new export into data/models/."""
    models.reload()
    ws.reset_provider()
    return {"reloaded": True, **models.status()["summary"]}


@router.get("/health")
async def health() -> Dict[str, Any]:
    """Cheap liveness probe — no model loading, no disk walk."""
    return {"status": "ok", "uptime_s": round(time.time() - STARTED_AT, 1)}


@router.get("/metrics")
async def metrics() -> Dict[str, Any]:
    """The §23 demo metrics, measured rather than asserted.

    Only numbers this process actually observed appear here.  Compute-unit and
    NPU utilisation come from Qualcomm's profiling tools on the device and are
    reported as unavailable until a Workbench profile has been imported —
    inventing them would be exactly the fake Snapdragon claim §4 forbids.
    """
    rows = db.query(
        "SELECT tool_name, COUNT(*) AS calls, AVG(duration_ms) AS avg_ms,"
        " MIN(duration_ms) AS min_ms, MAX(duration_ms) AS max_ms"
        " FROM tool_calls GROUP BY tool_name ORDER BY calls DESC")
    status = models.status()
    live = sessions.active()
    return {
        "latency": collector.snapshot(),
        "host": collector.host(),
        "camera": {
            "sessions": [{"session_id": s["session_id"], "camera_fps": s["camera_fps"],
                          "tracking_fps": s["tracking_fps"],
                          "detector_fps": s["detector_fps"],
                          "frames_per_vlm_call": s["frames_per_vlm_call"]}
                         for s in live],
            "note": "Measured per live session. Empty when no camera session is open.",
        },
        "tool_latency": [
            {"tool": r["tool_name"], "calls": r["calls"],
             "avg_ms": round(r["avg_ms"] or 0, 2),
             "min_ms": round(r["min_ms"] or 0, 2), "max_ms": round(r["max_ms"] or 0, 2)}
            for r in rows
        ],
        "model_load_ms": {
            role: v.get("load_ms") for role, v in status["roles"].items()
            if v.get("load_ms") is not None
        },
        "accelerators": {role: {"accelerator": v["accelerator"], "npu": v["npu"],
                                "synthetic": v["synthetic"]}
                         for role, v in status["roles"].items()},
        "live": live,
        "unavailable_metrics": {
            "npu_utilisation": "requires a Qualcomm AI Hub Workbench profile on the target device",
            "gpu_utilisation": "requires a platform profiler",
            "tokens_per_second": "reported once a real VLM adapter is serving generation; "
                                 "the offline stand-in generates no tokens",
        },
        "note": "Latency and host figures are measured by this process and reset when it "
                "restarts. Nothing here is estimated — what cannot be measured is listed "
                "under unavailable_metrics rather than filled in.",
    }

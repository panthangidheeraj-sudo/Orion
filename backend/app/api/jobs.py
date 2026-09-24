"""Jobs, machines, inspections, findings, measurements, memories, reports (§13, §14)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from app.agent.tool_registry import registry as tool_registry
from app.logging_setup import get_logger
from app.memory import memory_service as M
from app.memory import sqlite as db
from app.schemas.memory import (
    FindingCreate, InspectionCreate, JobCreate, JobUpdate, MachineCreate,
    MeasurementCreate, MemoryCreate, ReportCreate,
)

log = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["jobs"])


# --------------------------------------------------------------------- user

@router.get("/user")
async def get_user() -> Dict[str, Any]:
    """The local technician and the durable preferences memory has accepted (§13)."""
    return M.user_profile()


@router.patch("/user")
async def update_user(display_name: Optional[str] = Query(None, max_length=120)) -> Dict[str, Any]:
    return M.ensure_user(display_name)


# ----------------------------------------------------------------- machines

@router.get("/machines")
async def list_machines() -> Dict[str, Any]:
    rows = M.list_machines()
    return {"machines": rows, "count": len(rows)}


@router.post("/machines")
async def create_machine(req: MachineCreate) -> Dict[str, Any]:
    return M.upsert_machine(**req.model_dump())


# --------------------------------------------------------------------- jobs

@router.post("/jobs")
async def create_job(req: JobCreate) -> Dict[str, Any]:
    machine_id = req.machine_id
    if req.machine and not machine_id:
        machine_id = M.upsert_machine(**req.machine.model_dump())["id"]
    return M.create_job(req.title, machine_id=machine_id, status=req.status,
                        summary=req.summary)


@router.get("/jobs")
async def list_jobs(machine_id: Optional[str] = Query(None),
                    limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
    rows = M.list_jobs(machine_id, limit)
    return {"jobs": rows, "count": len(rows)}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> Dict[str, Any]:
    """Full job history — what the agent retrieves when a machine is reopened."""
    return M.job_history(job_id)


@router.patch("/jobs/{job_id}")
async def update_job(job_id: str, req: JobUpdate) -> Dict[str, Any]:
    return M.update_job(job_id, **req.model_dump(exclude_none=True))


# -------------------------------------------------------------- inspections

@router.post("/inspections")
async def start_inspection(req: InspectionCreate) -> Dict[str, Any]:
    return M.start_inspection(req.job_id, req.mode)


@router.post("/inspections/{inspection_id}/end")
async def end_inspection(inspection_id: str, summary: Optional[str] = None) -> Dict[str, Any]:
    return M.end_inspection(inspection_id, summary)


@router.post("/findings")
async def create_finding(req: FindingCreate) -> Dict[str, Any]:
    return M.save_finding(req.inspection_id, req.description, type=req.type,
                          confidence=req.confidence, source=req.source)


@router.post("/measurements")
async def create_measurement(req: MeasurementCreate) -> Dict[str, Any]:
    """A value is mandatory: §18 — never fabricate measurements."""
    return M.save_measurement(req.inspection_id, req.name, req.value,
                              unit=req.unit, source=req.source)


# ----------------------------------------------------------------- memories

@router.get("/memories")
async def list_memories(job_id: Optional[str] = Query(None),
                        memory_type: Optional[str] = Query(None),
                        limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
    rows = M.list_memories(job_id, memory_type, limit)
    return {"memories": rows, "count": len(rows)}


@router.post("/memories")
async def create_memory(req: MemoryCreate) -> Dict[str, Any]:
    """Subject to the §13 write policy — speculation is refused with a reason."""
    return await M.save_memory(
        memory_type=req.memory_type, content=req.content, confidence=req.confidence,
        source={**req.source, "origin": req.source.get("origin", "client")},
        job_id=req.job_id, confirmed=req.confirmed)


@router.delete("/memories/{memory_id}")
async def forget_memory(memory_id: str) -> Dict[str, Any]:
    return M.forget_memory(memory_id)


# ------------------------------------------------------------------ reports

@router.post("/reports")
async def create_report(req: ReportCreate) -> Dict[str, Any]:
    return await tool_registry.call("create_service_report", {
        "job_id": req.job_id, "title": req.title, "summary": req.summary,
        "recommendations": req.recommendations,
    }, context={"job_id": req.job_id})


@router.get("/reports")
async def list_reports(job_id: Optional[str] = Query(None)) -> Dict[str, Any]:
    if job_id:
        rows = db.query("SELECT * FROM reports WHERE job_id = ? ORDER BY created_at DESC",
                        (job_id,))
    else:
        rows = db.query("SELECT * FROM reports ORDER BY created_at DESC LIMIT 200")
    for r in rows:
        r.pop("path", None)
    return {"reports": rows, "count": len(rows)}


@router.get("/reports/{report_id}")
async def get_report(report_id: str) -> Dict[str, Any]:
    from pathlib import Path

    from app.errors import NotFound

    row = db.query_one("SELECT * FROM reports WHERE id = ?", (report_id,))
    if not row:
        raise NotFound("no such report", report_id=report_id)
    path = Path(row.pop("path"))
    markdown = path.read_text(encoding="utf-8") if path.exists() else ""
    return {**row, "markdown": markdown}

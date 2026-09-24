"""Action tools (§15): ask the technician, build a checklist, write a report.

Reports are written to ``data/reports/`` as Markdown plus a self-contained
HTML file.  Everything in a report comes from the local store — findings,
measurements and document references that were actually recorded.  Nothing is
invented to fill a heading; an empty section says it is empty.
"""

from __future__ import annotations

import html
import json
from typing import Any, Dict, List, Optional

from app.agent.tool_registry import registry as tools
from app.config import settings
from app.logging_setup import get_logger
from app.memory import memory_service as M
from app.memory import sqlite as db
from app.util import contained_path, new_id, safe_filename, utc_now

log = get_logger(__name__)

CHECKLIST_TEMPLATES: Dict[str, List[str]] = {
    "general": [
        "Record the machine identity from the nameplate (manufacturer, model, serial)",
        "Photograph the machine as found, including the affected area",
        "Note the reported symptom in the technician's own words",
        "Check for loose fasteners, damaged cabling and fluid traces",
        "Record ambient conditions if they could be relevant",
    ],
    "electrical": [
        "Confirm isolation, lock-out/tag-out applied and proven dead",
        "Inspect terminals for discolouration, looseness and arcing marks",
        "Measure supply voltage on each phase at the incoming terminals",
        "Measure running current per phase against the nameplate rating",
        "Measure insulation resistance winding-to-earth",
        "Verify the protection device setting against the nameplate",
    ],
    "mechanical": [
        "Confirm isolation and that rotation has stopped",
        "Check shaft end-float and radial play by hand",
        "Measure vibration at the drive and non-drive end bearings",
        "Check coupling alignment and condition",
        "Check mounting bolt torque and for soft foot",
        "Inspect lubrication condition and quantity",
    ],
    "thermal": [
        "Record surface temperature at the housing and bearing ends",
        "Record the ambient temperature for comparison",
        "Verify the cooling path is clear and the fan turns freely",
        "Check load against the duty rating",
        "Inspect for heat discolouration or a burnt smell",
    ],
}


@tools.tool(
    "ask_user",
    "Ask the technician one targeted question when a specific measurement, "
    "photograph or confirmation is required to go further. Use this rather "
    "than guessing.",
    {"type": "object", "additionalProperties": False,
     "required": ["question"],
     "properties": {
         "question": {"type": "string", "minLength": 6, "maxLength": 400},
         "why": {"type": "string", "maxLength": 300,
                 "description": "What this answer will let you rule in or out."},
         "expects": {"type": "string", "maxLength": 60,
                     "description": "measurement | photo | confirmation | text"},
         "unit": {"type": "string", "maxLength": 16},
     }},
    category="action")
async def ask_user(question: str, why: Optional[str] = None,
                   expects: str = "text", unit: Optional[str] = None):
    return {"question": question.strip(), "why": why, "expects": expects, "unit": unit,
            "awaiting_user": True, "source": "agent"}


@tools.tool(
    "create_inspection_checklist",
    "Build an ordered inspection checklist for this machine and symptom.",
    {"type": "object", "additionalProperties": False,
     "properties": {
         "focus": {"type": "array",
                   "description": "Any of: general, electrical, mechanical, thermal."},
         "machine": {"type": "string", "maxLength": 160},
         "symptom": {"type": "string", "maxLength": 300},
     }},
    category="action")
async def create_inspection_checklist(focus: Optional[List[str]] = None,
                                      machine: Optional[str] = None,
                                      symptom: Optional[str] = None):
    keys = [f for f in (focus or ["general"]) if f in CHECKLIST_TEMPLATES] or ["general"]
    if "general" not in keys:
        keys.insert(0, "general")
    items: List[Dict[str, Any]] = []
    for key in keys:
        for step in CHECKLIST_TEMPLATES[key]:
            items.append({"group": key, "step": step, "done": False})
    return {"checklist": items, "count": len(items), "groups": keys,
            "machine": machine, "symptom": symptom,
            "note": "General field-service sequence. Follow the manufacturer's procedure "
                    "for this machine where it differs.",
            "source": "agent"}


@tools.tool(
    "create_service_report",
    "Write a service report for a job from what has actually been recorded: "
    "findings, measurements, document references and outcome.",
    {"type": "object", "additionalProperties": False,
     "required": ["job_id"],
     "properties": {
         "job_id": {"type": "string", "maxLength": 64},
         "title": {"type": "string", "maxLength": 160},
         "summary": {"type": "string", "maxLength": 3000},
         "recommendations": {"type": "array"},
     }},
    category="action", mutates=True)
async def create_service_report(job_id: str, title: Optional[str] = None,
                                summary: Optional[str] = None,
                                recommendations: Optional[List[str]] = None,
                                context: Dict[str, Any] = None):
    history = M.job_history(job_id)
    job, machine = history["job"], history["machine"]
    report_id = new_id("rep")
    heading = title or f"Service report — {job.get('title') or job_id}"

    md = _markdown(heading, history, summary, recommendations or [])
    stem = safe_filename(f"{report_id}", fallback=report_id)
    md_path = contained_path(settings.reports_dir, f"{stem}.md")
    html_path = contained_path(settings.reports_dir, f"{stem}.html")
    md_path.write_text(md, encoding="utf-8")
    html_path.write_text(_html(heading, md), encoding="utf-8")

    db.insert("reports", {
        "id": report_id, "job_id": job_id,
        "inspection_id": (context or {}).get("inspection_id"),
        "title": heading, "format": "markdown+html", "path": str(md_path),
        "summary": (summary or "")[:2000], "created_at": utc_now(),
    })
    M.update_job(job_id, summary=summary or job.get("summary"))
    log.info("report %s written for job %s", report_id, job_id)

    return {
        "report_id": report_id, "title": heading, "job_id": job_id,
        "markdown": md, "formats": ["markdown", "html"],
        "findings": len(history["findings"]), "measurements": len(history["measurements"]),
        "machine": (machine or {}).get("name"),
        "source": "local_reports",
    }


def _markdown(heading: str, h: Dict[str, Any], summary: Optional[str],
              recommendations: List[str]) -> str:
    job, machine = h["job"], h["machine"]
    L: List[str] = [f"# {heading}", "",
                    f"*Generated {utc_now()} — VisionField Copilot, on device.*", ""]

    L += ["## Machine", ""]
    if machine:
        for label, key in (("Name", "name"), ("Manufacturer", "manufacturer"),
                           ("Model", "model"), ("Serial", "serial_number")):
            if machine.get(key):
                L.append(f"- **{label}:** {machine[key]}")
    else:
        L.append("- Not identified. No nameplate was confirmed during this job.")
    L.append("")

    L += ["## Job", "", f"- **Title:** {job.get('title') or '—'}",
          f"- **Status:** {job.get('status')}",
          f"- **Opened:** {job.get('created_at')}", ""]

    if summary:
        L += ["## Summary", "", summary, ""]

    L += ["## Inspections", ""]
    if h["inspections"]:
        for i in h["inspections"]:
            span = f"{i['started_at']} → {i['ended_at'] or 'open'}"
            L.append(f"- `{i['mode']}` {span}" + (f" — {i['summary']}" if i.get("summary") else ""))
    else:
        L.append("- None recorded.")
    L.append("")

    L += ["## Findings", ""]
    if h["findings"]:
        for f in h["findings"]:
            conf = f" _(confidence {f['confidence']:.2f})_" if f.get("confidence") else ""
            L.append(f"- **{f.get('type') or 'observation'}:** {f['description']}{conf}")
    else:
        L.append("- None recorded.")
    L.append("")

    L += ["## Measurements", ""]
    if h["measurements"]:
        L += ["| Name | Value | Unit | Source | Taken |", "|---|---|---|---|---|"]
        for m in h["measurements"]:
            L.append(f"| {m['name']} | {m['value']} | {m.get('unit') or ''} | "
                     f"{m.get('source') or ''} | {m['created_at']} |")
    else:
        L.append("- None recorded. No values have been estimated to fill this section.")
    L.append("")

    L += ["## Durable memory from this job", ""]
    if h["memories"]:
        for m in h["memories"]:
            L.append(f"- _{m['memory_type']}_ — {m['content']}")
    else:
        L.append("- None stored.")
    L.append("")

    if recommendations:
        L += ["## Recommendations", ""] + [f"1. {r}" for r in recommendations] + [""]

    if h.get("prior_jobs_on_machine"):
        L += ["## Earlier work on this machine", ""]
        for p in h["prior_jobs_on_machine"]:
            L.append(f"- {p['created_at'][:10]} — {p.get('title')} ({p.get('status')})")
        L.append("")

    L += ["---", "",
          "Generated from locally recorded evidence only. Figures that were not measured "
          "are marked as requiring confirmation. This report is not a substitute for the "
          "manufacturer's authorised procedure."]
    return "\n".join(L)


def _html(title: str, markdown: str) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>"
        "<style>body{background:#000;color:#F2F3F4;font:15px/1.65 ui-sans-serif,system-ui,"
        "sans-serif;max-width:820px;margin:0 auto;padding:48px 24px}"
        "h1,h2{font-weight:600;letter-spacing:-.01em}h2{margin-top:2em;font-size:17px;"
        "color:#C4C8CE}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #343841;padding:6px 10px;text-align:left;font-size:13px}"
        "hr{border:0;border-top:1px solid #343841;margin:2em 0}"
        "code{background:#1A1C20;padding:1px 5px;border-radius:4px}</style></head><body>"
        f"<pre style='white-space:pre-wrap;font:inherit'>{html.escape(markdown)}</pre>"
        "</body></html>"
    )

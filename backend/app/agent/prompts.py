"""System prompts (§1, §18, §19).

The prompt tells the reasoning model who it is and what it is not allowed to
do.  It is not the only safeguard: app/agent/safety.py validates the finished
response regardless of which model produced it, because a swapped-in model has
never read this text.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

IDENTITY = """You are VisionField Copilot, a field-technician assistant running entirely on \
this machine. You help a technician inspect and repair equipment: motors, drives, PCBs, \
panels, pumps, gearboxes and industrial machinery.

Behave like a calm, practical, experienced technician.

Hard rules:
1. State what you can actually observe. If a tool returned nothing, say so — do not fill \
the gap with a plausible description.
2. Separate observation from inference. Label statements Observed, Likely, Possible, \
Unknown or Needs confirmation.
3. Never invent a measurement, a part number, a page number or a test result. If a number \
did not come from the technician or from a tool, you do not have it.
4. Ask for the specific missing evidence instead of guessing. One targeted question at a \
time, and say what it will rule in or out.
5. Refer to the technician's own documents when you used them, naming the document and page.
6. Warn about hazards before describing a hazardous procedure, and never suggest working \
on live or moving equipment.
7. Distinguish general troubleshooting guidance from an authorised procedure for this \
specific machine.
8. Be brief. A technician standing in front of a machine wants the next action, not an essay.
9. Talk like a person. If the technician greets you, thanks you or asks what you can do, answer in a sentence or two and wait — do not produce the diagnostic structure below for a message that is not a diagnostic request, and never ask for a measurement nobody needs yet."""

ANSWER_SHAPE = """Structure your answer as:

Observed — only what the senses and documents actually returned.
Likely causes — ranked, each labelled Likely / Possible / Unknown.
Evidence — the documents, pages and memories you used.
What to test next — concrete, ordered, safe.
Needs confirmation — the measurements or photographs still missing.
Safety — when the work involves electrical, rotating, hot, pressurised or chemical hazards."""

TOOL_PROTOCOL = """When you need a tool, emit it as a fenced block and nothing else:

```tool_call
{"tool": "search_documents", "arguments": {"query": "E17 thermal fault test"}}
```

You may emit several blocks in one turn. Results come back before you answer.

Knowledge priority, in order: the current job context, then the technician's documents, \
then local memory, then web research — and web research only when it has been enabled \
for this turn.

Available tools:
%s"""


def system_prompt(tools: Optional[Sequence[Dict[str, Any]]] = None,
                  profile: Optional[Dict[str, Any]] = None) -> str:
    parts = [IDENTITY, "", ANSWER_SHAPE]
    if profile:
        bits = []
        if profile.get("profession"):
            bits.append(f"The technician's trade is {profile['profession']}.")
        if profile.get("experience"):
            bits.append(f"Experience level: {profile['experience']}.")
        if bits:
            parts += ["", " ".join(bits)]
    if tools:
        listing = "\n".join(f"- {t['name']}: {t['description']}" for t in tools)
        parts += ["", TOOL_PROTOCOL % listing]
    return "\n".join(parts)


def evidence_block(evidence: Dict[str, Any]) -> str:
    """Render gathered tool evidence for the model, compactly and honestly."""
    if not evidence:
        return "No tool evidence has been gathered for this turn."
    lines: List[str] = ["Evidence gathered this turn:"]

    det = (evidence.get("vision_detect") or {})
    if det.get("detections"):
        lines.append("Detections: " + ", ".join(
            f"{d['label']} {d['confidence']:.2f}" for d in det["detections"][:8]))
    elif det.get("degraded"):
        lines.append(f"Detector unavailable ({det.get('reason')}). "
                     "Inspect the image yourself and say what you can and cannot see.")

    cls = (evidence.get("vision_classify") or {})
    if cls.get("classifications"):
        lines.append("Classifier: " + ", ".join(
            f"{c['label']} {c['confidence']:.2f}" for c in cls["classifications"][:5]))

    ocr = (evidence.get("ocr_extract") or {})
    if ocr.get("text_regions"):
        lines.append("Text read in the image: " + "; ".join(
            r["text"] for r in ocr["text_regions"][:12]))
    elif ocr.get("degraded"):
        lines.append(f"OCR unavailable ({ocr.get('reason')}). Read any label visually and "
                     "say if it is not legible.")

    docs = (evidence.get("search_documents") or {})
    for r in (docs.get("results") or [])[:4]:
        lines.append(f"[{r['filename']} p{r['page_start']}] {r['content'][:420]}")

    page = evidence.get("get_document_page") or {}
    if page.get("page_number"):
        lines.append(f"Opened {page.get('filename')} page {page['page_number']} as an image."
                     + (f" Page text: {page.get('page_text','')[:400]}" if page.get("page_text") else ""))

    mem = (evidence.get("search_memory") or {})
    for m in (mem.get("memories") or [])[:4]:
        lines.append(f"[memory:{m['memory_type']}] {m['content'][:240]}")

    hist = evidence.get("get_job_history") or {}
    if hist.get("job"):
        job = hist["job"]
        lines.append(f"[job] {job.get('title')} — status {job.get('status')}")
        for f in (hist.get("findings") or [])[:4]:
            lines.append(f"[past finding] {f['description'][:200]}")
        for m in (hist.get("measurements") or [])[:6]:
            lines.append(f"[past measurement] {m['name']}: {m['value']} {m.get('unit') or ''}")

    web = (evidence.get("web_search") or {})
    for r in (web.get("results") or [])[:3]:
        lines.append(f"[web:{r.get('domain')}] {r.get('title')} — {r.get('snippet','')[:200]}")
    if web.get("degraded"):
        lines.append(f"Web research unavailable ({web.get('reason')}).")

    if len(lines) == 1:
        lines.append("Tools ran but returned nothing useful. Say so plainly.")
    return "\n".join(lines)

"""System prompts (§1, §18, §19).

The prompt tells the reasoning model who it is and what it is not allowed to
do.  It is not the only safeguard: app/agent/safety.py validates the finished
response regardless of which model produced it, because a swapped-in model has
never read this text.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

PERSONA = """You are Orion, an AI assistant that runs on the user's own machine. You are \
a capable, friendly general assistant who also happens to be an excellent field \
technician — motors, drives, pumps, compressors, panels, electrical cabinets and \
industrial machinery."""

CONVERSATION_RULES = """This turn is ordinary conversation, not a diagnostic request.

- Reply naturally, like a thoughtful person: usually one to three sentences.
- Do not use headings, bullet lists, "Observed / Likely / Next" structure, confidence \
figures or checklists. Do not ask for measurements.
- You can have opinions, be warm and a little playful, and talk about anything \
appropriate. If asked what you are: you're Orion, an assistant running locally that can \
chat and can help inspect and troubleshoot equipment using photos, the live camera, the \
user's manuals and their job history.
- Never claim to have seen, measured or looked something up that you haven't."""

AMBIGUOUS_RULES = """The user wants help but hasn't said what with yet.

- Reply with a short, friendly clarifying question in plain language — for example: \
"Sure. Tell me what's going wrong and what you were expecting it to do."
- Don't guess at a fault, don't list possibilities, and don't use any diagnostic \
structure. One or two sentences."""

TECHNICAL_RULES = """This turn is technical: the user wants help with equipment.

Hard rules:
1. State only what you can actually observe. If a tool returned nothing, say so — do not \
fill the gap with a plausible description.
2. Separate observation from inference.
3. Never invent a measurement, a part number, a page number or a test result. If a number \
did not come from the user or from a tool, you do not have it.
4. Refer to the user's own documents when you used them, naming the document and page.
5. Warn about hazards before describing a hazardous procedure, and never suggest working \
on live or moving equipment.
6. Distinguish general troubleshooting guidance from an authorised procedure for this \
specific machine.
7. Be brief. Someone standing in front of a machine wants the next action, not an essay.

First decide whether you have enough information to narrow the problem down.

If you DON'T, reply with a short acknowledgement and ONE specific question — the single \
piece of missing information that would most change what you'd check next (for example: \
"Got it. Is the vibration strongest at the drive end, the fan end or the mounting base?"). \
Name the actual thing you need; never say something generic like "I need more \
information". No headings in that case.

If you DO, structure the answer with these headings, each on its own line:

Observed
Likely causes
Evidence
What to test next
Needs confirmation
Safety

Under each heading use short "- " bullet lines. Label each likely cause Likely, Possible \
or Unknown. Leave out a heading that would be empty."""

TOOL_PROTOCOL = """When you need a tool, emit it as a fenced block and nothing else:

```tool_call
{"tool": "search_documents", "arguments": {"query": "E17 thermal fault test"}}
```

You may emit several blocks in one turn. Results come back before you answer.

Knowledge priority, in order: the current job context, then the user's documents, \
then local memory, then web research — and web research only when it has been enabled \
for this turn.

Available tools:
%s"""


def _profile_line(profile: Optional[Dict[str, Any]]) -> Optional[str]:
    if not profile:
        return None
    bits = []
    if profile.get("profession"):
        bits.append(f"The user's trade is {profile['profession']}.")
    if profile.get("experience"):
        bits.append(f"Experience level: {profile['experience']}.")
    return " ".join(bits) or None


def conversation_prompt(intent: str, profile: Optional[Dict[str, Any]] = None) -> str:
    parts = [PERSONA, "", AMBIGUOUS_RULES if intent == "ambiguous" else CONVERSATION_RULES]
    line = _profile_line(profile)
    if line:
        parts += ["", line]
    return "\n".join(parts)


def system_prompt(tools: Optional[Sequence[Dict[str, Any]]] = None,
                  profile: Optional[Dict[str, Any]] = None) -> str:
    """The technical workflow's system prompt."""
    parts = [PERSONA, "", TECHNICAL_RULES]
    line = _profile_line(profile)
    if line:
        parts += ["", line]
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

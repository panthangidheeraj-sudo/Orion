"""Deterministic offline reasoner.

This is the adapter that runs when no VLM asset has been exported yet.  It is
not a language model and never pretends to be one: ``synthetic: true``,
``npu: false``, provider ``heuristic-offline``, and every surface that reports
model status says so.

What it genuinely does:

* picks tools from the request and the evidence already gathered, so the whole
  §2 orchestration loop — SEE → RETRIEVE → REASON → VERIFY → GUIDE → REMEMBER —
  is exercised end to end;
* composes the §18 technician structure strictly from evidence that tools
  actually returned;
* labels every statement Observed / Likely / Possible / Unknown / Needs
  confirmation;
* never invents a measurement, a part number or a page reference.

If the evidence is thin, the answer says the evidence is thin and asks for the
missing reading.  That is the correct behaviour for a field assistant, and it
is the behaviour a real VLM is held to as well.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from app.models.base import READY, ModelHealth, ReasoningProvider

# Technical token: error codes, part numbers, ratings — E17, NSK6203, 24VDC.
TECHNICAL_TOKEN = re.compile(r"\b(?=[a-z0-9-]*\d)(?=[a-z0-9-]*[a-z])[a-z0-9][a-z0-9-]{1,15}\b", re.I)
MEASURE_UNIT = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*(°?\s?[cf]\b|deg\b|celsius|volts?\b|vdc\b|vac\b|v\b|amps?\b|a\b|"
    r"ma\b|ohms?\b|hz\b|rpm\b|bar\b|psi\b|mm\b|kw\b|hp\b|db\b|mm/s\b)",
    re.I,
)
UNIT_CANON = {
    "c": "°C", "°c": "°C", "f": "°F", "°f": "°F", "deg": "°", "celsius": "°C",
    "v": "V", "volt": "V", "volts": "V", "vdc": "VDC", "vac": "VAC",
    "a": "A", "amp": "A", "amps": "A", "ma": "mA", "ohm": "Ω", "ohms": "Ω",
    "hz": "Hz", "rpm": "rpm", "bar": "bar", "psi": "psi", "mm": "mm",
    "kw": "kW", "hp": "hp", "db": "dB", "mm/s": "mm/s",
}

# General field-service reasoning, not a manufacturer procedure (§19).
SYMPTOMS: List[Dict[str, Any]] = [
    {
        "key": "overheating",
        "cues": ["overheat", "hot", "burning smell", "thermal", "temperature high", "scorch"],
        "causes": [("Restricted cooling — blocked airflow, fouled fins, failed fan", "Likely"),
                   ("Sustained overload or duty beyond rating", "Likely"),
                   ("Bearing friction or misalignment adding mechanical load", "Possible"),
                   ("Degraded winding insulation drawing excess current", "Possible")],
        "tests": ["Surface temperature at the housing and at the bearing end, with the ambient noted",
                  "Running current on each phase against the nameplate rating",
                  "Airflow path and fan rotation with the machine isolated",
                  "Insulation resistance if the smell suggests winding damage"],
        "measurements": [("temperature", "°C"), ("current", "A")],
    },
    {
        "key": "vibration",
        "cues": ["vibrat", "shake", "wobble", "unbalanc", "runout"],
        "causes": [("Bearing wear or damage", "Likely"),
                   ("Shaft or coupling misalignment", "Likely"),
                   ("Rotor or driven-load imbalance", "Possible"),
                   ("Loose mounting feet or soft foot", "Possible")],
        "tests": ["Vibration amplitude at the drive and non-drive end bearings",
                  "Coupling alignment with a dial gauge or laser",
                  "Mounting bolt torque and shim condition",
                  "Compare the vibration signature against the last recorded baseline"],
        "measurements": [("vibration", "mm/s")],
    },
    {
        "key": "noise",
        "cues": ["noise", "noisy", "grind", "squeal", "rattle", "knock", "whine", "hum"],
        "causes": [("Bearing degradation — grinding or rumbling under load", "Likely"),
                   ("Contact between rotating and stationary parts", "Possible"),
                   ("Loose fastener or guard resonating", "Possible"),
                   ("Electrical hum from supply imbalance if the pitch tracks line frequency", "Possible")],
        "tests": ["Listen at each bearing with a stethoscope or probe, machine running",
                  "Coast-down test: note whether the noise follows shaft speed",
                  "Guard and fastener check with the machine isolated"],
        "measurements": [("vibration", "mm/s"), ("sound_level", "dB")],
    },
    {
        "key": "electrical_trip",
        "cues": ["trip", "breaker", "fuse", "overcurrent", "short", "earth fault", "rcd"],
        "causes": [("Winding or cable insulation failure to earth", "Likely"),
                   ("Mechanical load beyond rating causing sustained overcurrent", "Likely"),
                   ("Protection device set below actual duty or itself degraded", "Possible")],
        "tests": ["Insulation resistance winding-to-earth, machine isolated and proven dead",
                  "Running current per phase against the nameplate",
                  "Protection setting against the nameplate full-load current",
                  "Cable and gland condition along the run"],
        "measurements": [("insulation_resistance", "Ω"), ("current", "A")],
    },
    {
        "key": "leak",
        "cues": ["leak", "drip", "seep", "weep", "oil on", "coolant", "hydraulic fluid"],
        "causes": [("Seal or gasket degradation", "Likely"),
                   ("Fitting loosened by vibration", "Likely"),
                   ("Overpressure or blocked return path", "Possible"),
                   ("Housing or line damage", "Possible")],
        "tests": ["Clean, run and re-inspect to find the true origin rather than where it collects",
                  "System pressure against the rated working pressure",
                  "Fitting torque and line routing for chafe points"],
        "measurements": [("pressure", "bar")],
    },
    {
        "key": "no_start",
        "cues": ["won't start", "wont start", "not starting", "no start", "dead", "no power",
                 "does not run", "doesn't run"],
        "causes": [("Supply not present at the terminals", "Likely"),
                   ("Control circuit interlock, E-stop or permissive not satisfied", "Likely"),
                   ("Contactor or starter fault", "Possible"),
                   ("Mechanical seizure preventing rotation", "Possible")],
        "tests": ["Supply voltage at the incoming terminals, using safe working practice",
                  "Control-circuit interlocks and E-stop states in sequence",
                  "Shaft rotation by hand with the machine isolated",
                  "Starter and contactor contact condition"],
        "measurements": [("voltage", "V")],
    },
    {
        "key": "error_code",
        "cues": ["error", "fault code", "alarm", "code", "flashing", "blink"],
        "causes": [("The controller has latched a specific fault — its meaning is defined "
                    "by the manufacturer's code table", "Needs confirmation")],
        "tests": ["Read the exact code text from the display or nameplate label",
                  "Look the code up in the manufacturer's manual for this model",
                  "Note what the machine was doing when the code appeared"],
        "measurements": [],
    },
]

SAFETY_HINTS = {
    "electrical_trip": "isolation and proving dead before any winding or cable test",
    "no_start": "isolation before checking rotation by hand",
    "overheating": "hot surfaces; allow cooling or use appropriate protection",
    "leak": "pressure energy; depressurise before breaking any joint",
}


def extract_measurements(text: str) -> List[Dict[str, Any]]:
    """Read measurements the *technician* stated.  Nothing is ever invented."""
    out: List[Dict[str, Any]] = []
    for m in MEASURE_UNIT.finditer(text or ""):
        raw_unit = m.group(2).replace(" ", "").lower().lstrip("°")
        out.append({
            "value": float(m.group(1)),
            "unit": UNIT_CANON.get(raw_unit, m.group(2).strip()),
            "text": m.group(0).strip(),
            "source": "technician_statement",
        })
    return out


def match_symptoms(text: str) -> List[Dict[str, Any]]:
    low = (text or "").lower()
    return [s for s in SYMPTOMS if any(c in low for c in s["cues"])]


def technical_tokens(text: str) -> List[str]:
    seen: List[str] = []
    for t in TECHNICAL_TOKEN.findall(text or ""):
        u = t.upper()
        if u not in seen and not u.isdigit():
            seen.append(u)
    return seen[:8]


class HeuristicReasoningProvider(ReasoningProvider):
    """Rule-based technician reasoning over tool evidence."""

    def __init__(self) -> None:
        super().__init__("heuristic_offline_v1", "heuristic-offline")

    def _load(self) -> None:
        self._health = ModelHealth(
            role=self.role, provider=self.provider, model_id=self.model_id, status=READY,
            runtime="python", accelerator="cpu", npu=False, synthetic=True,
            detail={
                "note": "Not a language model. Deterministic tool selection and "
                        "evidence-bound composition so the agent loop runs before a "
                        "VLM asset is exported. Produces no NPU metrics.",
                "symptom_patterns": len(SYMPTOMS),
            },
        )

    def capabilities(self) -> Dict[str, Any]:
        return {**super().capabilities(), "streaming": False, "images": False,
                "tool_calls": "rule-based", "synthetic": True}

    # ------------------------------------------------------------------ loop
    async def generate(self, messages, images=None, tools=None, context=None) -> Dict[str, Any]:
        self.require_ready()
        ctx = dict(context or {})
        question = _last_user_text(messages)
        evidence = ctx.get("evidence") or {}
        tool_names = {t.get("name") for t in (tools or [])}
        rounds = int(ctx.get("round", 0))

        # A page we opened from a manual is not a photograph the technician
        # took, so it must not make the answer talk about "your image".
        has_photos = bool(ctx.get("image_ids"))
        calls = self._choose_tools(question, ctx, evidence, tool_names, rounds, has_photos)
        if calls:
            return {"text": "", "tool_calls": calls, "model": self.model_id,
                    "usage": {"mode": "tool_selection", "round": rounds}}

        body, sections, meta = self._compose(question, ctx, evidence, has_photos)
        return {"text": body, "tool_calls": [], "sections": sections,
                "model": self.model_id, "meta": meta,
                "usage": {"mode": "compose", "round": rounds}}

    def _choose_tools(self, question, ctx, evidence, tool_names, rounds, has_images) -> List[Dict[str, Any]]:
        if rounds >= 2:
            return []
        calls: List[Dict[str, Any]] = []
        done = set(evidence.keys())
        tokens = technical_tokens(question)

        if rounds == 0:
            if has_images and "vision_detect" in tool_names and "vision_detect" not in done:
                calls.append({"tool": "vision_detect", "arguments": {}})
            if has_images and "ocr_extract" in tool_names and "ocr_extract" not in done:
                calls.append({"tool": "ocr_extract", "arguments": {}})
            if ctx.get("document_count") and "search_documents" in tool_names:
                calls.append({"tool": "search_documents",
                              "arguments": {"query": _retrieval_query(question, tokens)}})
            if "search_memory" in tool_names:
                calls.append({"tool": "search_memory", "arguments": {"query": question[:200]}})
            if ctx.get("job_id") and "get_job_history" in tool_names:
                calls.append({"tool": "get_job_history", "arguments": {"job_id": ctx["job_id"]}})
            # §16 fixes the order: job context, then the technician's documents,
            # then local memory, and only then the web. So web search is NOT
            # offered in this round — it is considered in round 1, once we know
            # whether the local knowledge actually answered the question.
            return calls

        # Round 1 — web research, but only if local knowledge came up short.
        if ctx.get("web_search_requested") and "web_search" in tool_names \
                and "web_search" not in done and _local_knowledge_thin(evidence):
            calls.append({"tool": "web_search",
                          "arguments": {"query": _retrieval_query(question, tokens)}})

        # §7's optional classification stage, once detection has a
        # region worth looking at more closely.
        detections = (evidence.get("vision_detect") or {}).get("detections") or []
        if detections and "vision_classify" in tool_names and "vision_classify" not in done:
            calls.append({"tool": "vision_classify",
                          "arguments": {"bbox": detections[0].get("bbox")}})

        # A diagram is worth opening only when the question is spatial
        # and retrieval actually put us on a page (§11).
        wants_page = any(w in question.lower() for w in
                         ("where", "which terminal", "diagram", "schematic", "wiring",
                          "pinout", "layout", "connector", "location", "test point"))
        hits = (evidence.get("search_documents") or {}).get("results") or []
        if wants_page and hits and "get_document_page" in tool_names \
                and "get_document_page" not in done:
            top = hits[0]
            page = top.get("page_start") or 1
            calls.append({"tool": "get_document_page",
                          "arguments": {"document_id": top.get("document_id"),
                                        "page_number": page}})
        return calls

    # --------------------------------------------------------------- compose
    def _compose(self, question, ctx, evidence, has_images):
        observed: List[str] = []
        detections = (evidence.get("vision_detect") or {}).get("detections") or []
        ocr = (evidence.get("ocr_extract") or {}).get("text_regions") or []
        doc_hits = (evidence.get("search_documents") or {}).get("results") or []
        page = evidence.get("get_document_page") or {}
        memories = (evidence.get("search_memory") or {}).get("memories") or []
        history = evidence.get("get_job_history") or {}
        web = (evidence.get("web_search") or {}).get("results") or []
        frame = (evidence.get("vision_detect") or {}).get("image") or {}

        # ---- Observed: only things a sense actually returned.
        if detections:
            top = ", ".join(
                f"{d['label']} ({d['confidence']:.2f})" for d in detections[:5])
            observed.append(f"Detector returned {len(detections)} object(s): {top}.")
        classes = (evidence.get("vision_classify") or {}).get("classifications") or []
        if classes:
            top = ", ".join(f"{c['label']} ({c['confidence']:.2f})" for c in classes[:3])
            observed.append(f"Classifier's best guesses for that region: {top}.")
        if ocr:
            readable = [t["text"] for t in ocr if t.get("text")][:8]
            if readable:
                observed.append("Text read from the image: " + "; ".join(readable) + ".")
        if frame.get("likely_blurred"):
            observed.append("The frame is low in edge detail — it may be out of focus or moving.")
        if frame.get("underexposed"):
            observed.append("The frame is underexposed; labels may not be readable.")
        if has_images and not detections and not ocr:
            observed.append(
                "An image was supplied, but no detector or OCR result is available on this "
                "machine, so nothing in it has been confirmed visually.")
        for quote in _manual_quotes(doc_hits, question):
            observed.append(quote)
        if page.get("page_text") and not doc_hits:
            observed.append(f"{page.get('filename')} page {page['page_number']} reads: "
                            f"\u201c{_clip(page['page_text'], 220)}\u201d")
        stated = extract_measurements(question)
        for m in stated:
            observed.append(f"You reported {m['text']}.")
        if not observed:
            observed.append("No sensor, image or document evidence has been gathered for this "
                            "question yet — the answer below is general guidance only.")

        # ---- Likely causes
        symptoms = match_symptoms(question)
        causes: List[Dict[str, str]] = []
        for s in symptoms:
            for text, label in s["causes"]:
                causes.append({"label": label, "text": text})
        if history.get("findings"):
            for f in history["findings"][:2]:
                causes.insert(0, {"label": "Observed",
                                  "text": f"Previously recorded on this job: {f.get('description')}"})
        if not causes:
            causes.append({"label": "Unknown",
                           "text": "The symptom described does not match a recognised pattern here. "
                                   "Describe what changed, when it started and what the machine "
                                   "was doing at the time."})

        # ---- Evidence
        refs: List[Dict[str, Any]] = []
        for h in doc_hits[:4]:
            refs.append({
                "kind": "document", "document_id": h.get("document_id"),
                "filename": h.get("filename"),
                "page": h.get("page_start"),
                "score": h.get("score"),
                "excerpt": (h.get("content") or "")[:220],
            })
        if page.get("page_number"):
            refs.append({"kind": "document_page", "document_id": page.get("document_id"),
                         "filename": page.get("filename"), "page": page.get("page_number"),
                         "image_available": bool(page.get("image_path"))})
        for m in memories[:3]:
            refs.append({"kind": "memory", "memory_id": m.get("id"),
                         "memory_type": m.get("memory_type"),
                         "excerpt": (m.get("content") or "")[:180],
                         "confidence": m.get("confidence")})
        for w in web[:3]:
            refs.append({"kind": "web", "title": w.get("title"), "url": w.get("url"),
                         "domain": w.get("domain"), "retrieved_at": w.get("retrieved_at")})

        # ---- Next tests
        tests: List[str] = []
        for s in symptoms:
            tests.extend(s["tests"])
        if doc_hits and not tests:
            tests.append(f"Follow the procedure on page {doc_hits[0].get('page_start')} of "
                         f"{doc_hits[0].get('filename')}.")
        if not tests:
            tests.append("Record the machine's nameplate details and the exact symptom, then "
                         "photograph the affected area so the inspection has a baseline.")
        seen: set = set()
        tests = [t for t in tests if not (t in seen or seen.add(t))][:6]

        # ---- What is still missing
        needed: List[str] = []
        have_units = {m["unit"] for m in stated}
        for s in symptoms:
            for name, unit in s["measurements"]:
                if unit not in have_units:
                    needed.append(f"{name.replace('_', ' ')} ({unit})")
        needed = list(dict.fromkeys(needed))[:4]
        if not detections and has_images:
            needed.append("a detector or OCR model so the image can be read automatically")
        if not doc_hits and ctx.get("document_count", 0) == 0:
            needed.append("the service manual for this machine, uploaded to the knowledge vault")

        # ---- Safety
        hazards = [SAFETY_HINTS[s["key"]] for s in symptoms if s["key"] in SAFETY_HINTS]

        sections = [
            {"kind": "observed", "title": "Observed", "items": observed},
            {"kind": "inferred", "title": "Likely causes",
             "items": [f"{c['label']}: {c['text']}" for c in causes[:6]]},
            {"kind": "next", "title": "What to test next", "items": tests},
        ]
        if needed:
            sections.append({"kind": "measure", "title": "Needs confirmation", "items": needed})
        if refs:
            sections.append({
                "kind": "ref", "title": "Evidence",
                "items": [_ref_line(r) for r in refs], "refs": refs,
            })

        confidence = _confidence(detections, ocr, doc_hits, memories, stated, symptoms)
        meta = {
            "confidence": confidence,
            "confidence_label": _confidence_label(confidence),
            "hazards": hazards,
            "symptoms": [s["key"] for s in symptoms],
            "measurements_stated": stated,
            "refs": refs,
            "synthetic": True,
        }
        return _flatten(sections), sections, meta


# Split on sentence ends only, never inside "4.3" or "6203-2RS" — a quote that
# starts mid-heading reads as if the manual said something it did not.
_SENT_SPLIT = re.compile(r"(?<=[A-Za-z0-9)\]\"\'])[.!?]+(?=\s+[A-Z0-9(\"\']|\s*$)")


def _sentences(text: str) -> List[str]:
    out, start = [], 0
    for m in _SENT_SPLIT.finditer(text or ""):
        out.append(text[start:m.end()].strip())
        start = m.end()
    tail = (text or "")[start:].strip()
    if tail:
        out.append(tail)
    return [s for s in out if s]


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def _manual_quotes(doc_hits: List[Dict[str, Any]], question: str) -> List[str]:
    """Pull the sentence that actually answers the question out of each hit.

    Citing "page 47" is not an answer. If the retrieved passage contains the
    error code or part number the technician asked about, the sentence carrying
    it is quoted verbatim, attributed, and left unparaphrased.
    """
    wanted = {t.upper() for t in technical_tokens(question)}
    out: List[str] = []
    for hit in doc_hits[:2]:
        content = hit.get("content") or ""
        exact = [t for t in (hit.get("exact_matches") or []) if t in wanted] or list(wanted)
        chosen = ""
        for sentence in _sentences(content) or [content]:
            upper = sentence.upper()
            if any(tok in upper for tok in exact):
                chosen = sentence.strip()
                break
        if not chosen:
            continue
        out.append(f"{hit.get('filename')} page {hit.get('page_start')} states: "
                   f"\u201c{_clip(chosen, 260)}\u201d")
    return out


def _local_knowledge_thin(evidence: Dict[str, Any]) -> bool:
    """Has the local material actually answered this?

    §16 makes web research the last resort, not a parallel source. It is worth
    reaching for only when the manuals returned nothing, returned nothing that
    matched the technician's exact token, or scored weakly — and when job
    memory had nothing either.
    """
    hits = (evidence.get("search_documents") or {}).get("results") or []
    memories = (evidence.get("search_memory") or {}).get("memories") or []
    history = (evidence.get("get_job_history") or {}).get("findings") or []
    if memories or history:
        return False
    if not hits:
        return True
    top = hits[0]
    if top.get("exact_matches"):
        return False
    return float(top.get("score") or 0.0) < 0.035


def _ref_line(r: Dict[str, Any]) -> str:
    if r["kind"] == "document":
        return f"{r.get('filename')} — page {r.get('page')}"
    if r["kind"] == "document_page":
        return f"{r.get('filename')} — page {r.get('page')} opened as an image"
    if r["kind"] == "memory":
        return f"Job memory ({r.get('memory_type')}): {r.get('excerpt')}"
    return f"{r.get('title')} — {r.get('domain')}"


def _flatten(sections: Sequence[Dict[str, Any]]) -> str:
    out: List[str] = []
    for s in sections:
        out.append(s["title"])
        out.extend(f"- {item}" for item in s["items"])
        out.append("")
    return "\n".join(out).strip()


def _confidence(detections, ocr, doc_hits, memories, stated, symptoms) -> float:
    score = 0.18
    if symptoms:
        score += 0.12
    if detections:
        score += 0.14
    if ocr:
        score += 0.12
    if doc_hits:
        score += 0.20 * min(1.0, (doc_hits[0].get("score") or 0.4) * 2)
    if memories:
        score += 0.08
    if stated:
        score += 0.10
    return round(min(score, 0.86), 2)


def _confidence_label(c: float) -> str:
    if c >= 0.7:
        return "Well supported"
    if c >= 0.5:
        return "Partly supported"
    if c >= 0.33:
        return "Weak evidence"
    return "Needs evidence"


def _last_user_text(messages: Sequence[Dict[str, Any]]) -> str:
    for m in reversed(list(messages or [])):
        if m.get("role") == "user":
            c = m.get("content")
            return c if isinstance(c, str) else " ".join(
                p.get("text", "") for p in c if isinstance(p, dict))
    return ""


def _retrieval_query(question: str, tokens: List[str]) -> str:
    return " ".join(dict.fromkeys(tokens + question.split()))[:220]

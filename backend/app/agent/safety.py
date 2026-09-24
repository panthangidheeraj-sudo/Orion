"""Safety layer (§19).

Two places, as the specification asks: a policy the agent is told about in its
prompt, and a validator that inspects the finished response before it leaves
the backend.  The validator is the one that matters, because it applies to any
reasoning provider — including one swapped in later that has never seen our
prompt.

It does three things:

* attaches the right hazard notice when the response touches a hazardous
  procedure;
* flags language that would have the technician work on live equipment, and
  rewrites the response to lead with isolation;
* flags fabricated measurements — a numeric reading asserted as fact that no
  tool and no technician statement ever produced.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from app.logging_setup import get_logger

log = get_logger(__name__)

HAZARDS = [
    {
        "key": "electrical",
        "pattern": re.compile(
            r"\b(terminal|winding|busbar|contactor|live|energi[sz]ed|voltage|mains|"
            r"phase|earth|ground fault|insulation resistance|megger|capacitor|"
            r"drive|inverter|vfd|panel|switchgear)\b", re.I),
        "notice": "Electrical hazard. Isolate the supply, apply lock-out/tag-out and prove dead "
                  "with a tester you have proven on a known source before touching any "
                  "conductor. Stored energy in drive capacitors can persist after isolation — "
                  "observe the manufacturer's discharge time.",
    },
    {
        "key": "rotating",
        "pattern": re.compile(
            r"\b(shaft|coupling|belt|pulley|fan|impeller|rotor|gearbox|spindle|"
            r"rotating|chain|sprocket)\b", re.I),
        "notice": "Rotating machinery. Isolate and confirm the shaft has come to rest before "
                  "removing a guard or reaching into the machine. Do not rely on the control "
                  "stop alone.",
    },
    {
        "key": "thermal",
        "pattern": re.compile(r"\b(hot|overheat|thermal|burn|scorch|steam|temperature above|"
                              r"\d{2,3}\s*°?\s?[cf]\b)", re.I),
        "notice": "Hot surfaces. Allow the machine to cool or use appropriate protection before "
                  "contact; take temperatures with a non-contact instrument where possible.",
    },
    {
        "key": "pressure",
        "pattern": re.compile(r"\b(hydraulic|pneumatic|pressure|accumulator|bar\b|psi\b|"
                              r"compressed air)\b", re.I),
        "notice": "Stored pressure. Depressurise the circuit and confirm zero pressure at the "
                  "gauge before breaking any joint. Hydraulic injection injuries are serious "
                  "even when the skin looks unbroken.",
    },
    {
        "key": "chemical",
        "pattern": re.compile(r"\b(coolant|solvent|electrolyte|acid|refrigerant|"
                              r"lubricant spill|fume)\b", re.I),
        "notice": "Chemical exposure. Check the substance's safety data sheet for handling, "
                  "ventilation and personal protective equipment before proceeding.",
    },
]

# Language that would put hands on live or moving equipment.
UNSAFE_INSTRUCTION = re.compile(
    r"\b(while (?:it(?:'s| is) )?(?:still )?(?:running|energi[sz]ed|live|powered)|"
    r"without isolating|no need to isolate|don'?t bother isolating|"
    r"touch the (?:live|energi[sz]ed) |bypass the (?:interlock|guard|e-?stop)|"
    r"remove the guard while|defeat the interlock)\b", re.I)

MEASUREMENT = re.compile(
    r"(?<![\w.])(\d{1,5}(?:\.\d+)?)\s?(°\s?[CF]|degrees?\s?[CF]?|V(?:AC|DC)?|A\b|mA\b|"
    r"k?Ω|ohms?\b|Hz\b|rpm\b|bar\b|psi\b|kW\b|mm/s\b|dB\b)", re.I)

PROFESSIONAL_NOTE = (
    "This is general troubleshooting guidance, not an authorised procedure for this "
    "specific machine. Follow the manufacturer's manual and your site's permit and "
    "competency requirements; some work is restricted to authorised persons."
)


def detect_hazards(text: str) -> List[Dict[str, str]]:
    found = []
    for h in HAZARDS:
        if h["pattern"].search(text or ""):
            found.append({"key": h["key"], "notice": h["notice"]})
    return found


def _known_numbers(evidence: Dict[str, Any], user_text: str) -> set:
    """Every number the pipeline can legitimately state."""
    known = set(re.findall(r"\d{1,5}(?:\.\d+)?", user_text or ""))

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 6:
            return
        if isinstance(node, str):
            known.update(re.findall(r"\d{1,5}(?:\.\d+)?", node))
        elif isinstance(node, (int, float)):
            known.add(str(node))
            known.add(str(int(node)) if float(node).is_integer() else str(node))
        elif isinstance(node, dict):
            for v in node.values():
                walk(v, depth + 1)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v, depth + 1)

    walk(evidence)
    return known


def review(text: str, evidence: Optional[Dict[str, Any]] = None,
           user_text: str = "", sections: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Validate a finished response.  Returns the (possibly amended) response."""
    evidence = evidence or {}
    notes: List[str] = []
    blocked: List[str] = []

    haystack = text or ""
    for s in sections or []:
        haystack += "\n" + "\n".join(str(i) for i in s.get("items", []))

    hazards = detect_hazards(haystack)

    unsafe = UNSAFE_INSTRUCTION.findall(haystack)
    if unsafe:
        blocked.append("instruction to work on live or moving equipment")
        log.warning("safety layer rewrote a response containing unsafe instruction(s)")

    known = _known_numbers(evidence, user_text)
    invented: List[str] = []
    for value, unit in MEASUREMENT.findall(haystack):
        if value not in known:
            invented.append(f"{value} {unit}".strip())
    # Ranges and thresholds quoted from a manual are fine; a bare assertion is not.
    invented = [v for v in dict.fromkeys(invented)][:6]

    amended = text
    if blocked:
        amended = (
            "Before anything else: isolate the machine, apply lock-out/tag-out and prove dead. "
            "Do not work on live or moving equipment.\n\n" + (text or "")
        )
        notes.append("Response was amended to lead with isolation.")
    if invented:
        notes.append(
            "These figures are not backed by a measurement in this session — treat them as "
            "values to confirm, not as readings: " + ", ".join(invented))

    return {
        "text": amended,
        "hazards": hazards,
        "hazard_notices": [h["notice"] for h in hazards],
        "professional_note": PROFESSIONAL_NOTE if hazards else None,
        "unverified_figures": invented,
        "blocked_patterns": blocked,
        "notes": notes,
        "safe": not blocked,
    }

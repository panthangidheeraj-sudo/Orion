"""The router: one model-driven decision about what the technician wants.

Before anything else happens on a turn, the configured reasoning model reads
the message *in context* — recent conversation, mode, attachments, profile —
and returns a strict JSON verdict:

    {"intent": "conversation" | "technical" | "ambiguous",
     "confidence": 0.0-1.0,
     "reason": "<internal, never shown>",
     "requires_safety_gate": false}

There are no keyword lists here and no regex fallback. Meaning comes from the
model. If no real language model is running (none installed, the local
server is down, or it keeps returning something that isn't the schema), the
router says so — `available=False` — and the orchestrator answers with a
plain "tell me more" instead of pretending it understood.

The only deterministic check on user input is the independent safety gate
(app/agent/safety.py `input_gate`), which runs separately and can only add a
safety-first preface. It never decides intent.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from app.errors import ModelUnavailable
from app.logging_setup import get_logger
from app.models.base import READY, ReasoningProvider

log = get_logger(__name__)

INTENTS = ("conversation", "technical", "ambiguous")

ROUTE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent", "confidence", "reason", "requires_safety_gate"],
    "properties": {
        "intent": {"type": "string", "enum": list(INTENTS)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string", "maxLength": 300},
        "requires_safety_gate": {"type": "boolean"},
    },
}

ROUTER_PROMPT = """You are the routing step of Orion, an AI assistant that is also an \
expert field technician (motors, pumps, drives, panels, compressors, electrical cabinets \
and other industrial equipment).

Read the user's latest message IN THE CONTEXT of the recent conversation, the mode and \
any attachments, and decide what they want right now:

- "conversation": ordinary chat — greetings, small talk, opinions, questions about Orion \
itself, reactions, general questions or requests (including summarising a document) that \
don't ask for help inspecting, diagnosing or repairing equipment.
- "technical": they want help with equipment — a fault or symptom, an inspection, reading \
a nameplate or label, identifying a part in a photo, a specification or procedure from a \
manual, or they are continuing a technical thread already under way (a short reply such \
as "yeah, exactly" or "drive end" continues the topic before it).
- "ambiguous": they want help but haven't said with what, so you would have to ask \
("something is wrong", "can you help?", "it isn't working", "what should I do?") — and \
nothing earlier in the conversation says what "it" is.

An attachment is a strong signal but not a verdict: a photo with "what do you think?" or \
"what is this?" is technical; a document with "summarise this" is conversation; a \
document with "what torque should I use?" is technical.

Set "requires_safety_gate" to true only if the message suggests an active physical \
hazard (fire, smoke, sparks or arcing, exposed live conductors, someone hurt or at risk).

Reply with ONLY a JSON object, no prose and no code fences:
{"intent": "conversation" | "technical" | "ambiguous", "confidence": <0..1>, \
"reason": "<one short internal sentence>", "requires_safety_gate": <true|false>}"""

MAX_HISTORY = 8
MAX_CHARS_PER_TURN = 600

_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


@dataclass
class RouteDecision:
    available: bool
    intent: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""                 # internal only — logged, never returned to the UI
    requires_safety_gate: bool = False
    failure: Optional[str] = None    # why the router could not decide
    attempts: int = 0
    raw: Dict[str, Any] = field(default_factory=dict)

    def public(self) -> Dict[str, Any]:
        """What the client may see: the decision, never the rationale."""
        return {"intent": self.intent, "confidence": round(self.confidence, 2),
                "available": self.available}


def is_language_model(reasoner: ReasoningProvider) -> bool:
    """True only for a real, loaded language model — never a stand-in."""
    h = reasoner.health()
    return h.status == READY and not h.synthetic


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """The first balanced top-level JSON object in `text`, if any."""
    text = _THINK.sub("", text or "").strip()
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        return obj if isinstance(obj, dict) else None
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def validate(obj: Any) -> Optional[Dict[str, Any]]:
    """Strict check against ROUTE_SCHEMA. Anything off-schema is rejected."""
    if not isinstance(obj, dict):
        return None
    if set(obj) != set(ROUTE_SCHEMA["required"]):
        return None
    intent, conf = obj.get("intent"), obj.get("confidence")
    reason, gate = obj.get("reason"), obj.get("requires_safety_gate")
    if intent not in INTENTS:
        return None
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not 0 <= conf <= 1:
        return None
    if not isinstance(reason, str) or len(reason) > 300:
        return None
    if not isinstance(gate, bool):
        return None
    return {"intent": intent, "confidence": float(conf), "reason": reason,
            "requires_safety_gate": gate}


def _context_block(mode: str, attachments: Sequence[Dict[str, Any]],
                   profile: Optional[Dict[str, Any]], job_title: Optional[str]) -> str:
    lines = [f"Mode: {'Live camera' if mode == 'live' else 'Normal chat'}."]
    if attachments:
        lines.append("Attached to this message: " + ", ".join(
            f"{a.get('kind', 'file')}" + (f" ({a['name']})" if a.get("name") else "")
            for a in attachments) + ".")
    else:
        lines.append("Nothing is attached to this message.")
    if job_title:
        lines.append(f"The conversation is linked to a job: {job_title}.")
    if profile and profile.get("profession"):
        lines.append(f"The user's trade: {profile['profession']}.")
    return "\n".join(lines)


def build_messages(message: str, history: Sequence[Dict[str, str]], mode: str,
                   attachments: Sequence[Dict[str, Any]],
                   profile: Optional[Dict[str, Any]] = None,
                   job_title: Optional[str] = None) -> List[Dict[str, str]]:
    recent = [h for h in history if h.get("role") in ("user", "assistant")][-MAX_HISTORY:]
    transcript = "\n".join(
        f"{h['role'].upper()}: {h['content'][:MAX_CHARS_PER_TURN]}" for h in recent
    ) or "(this is the first message)"
    return [
        {"role": "system", "content": ROUTER_PROMPT},
        {"role": "user", "content": (
            f"{_context_block(mode, attachments, profile, job_title)}\n\n"
            f"Recent conversation:\n{transcript}\n\n"
            f"Latest message:\n{message}\n\n"
            "Return the JSON object now.")},
    ]


async def route(reasoner: ReasoningProvider, message: str,
                history: Sequence[Dict[str, str]] = (), mode: str = "normal",
                attachments: Sequence[Dict[str, Any]] = (),
                profile: Optional[Dict[str, Any]] = None,
                job_title: Optional[str] = None, max_attempts: int = 2) -> RouteDecision:
    if not is_language_model(reasoner):
        return RouteDecision(available=False, failure="no language model is running")

    messages = build_messages(message, history, mode, attachments, profile, job_title)
    last_text = ""
    for attempt in range(1, max_attempts + 1):
        try:
            result = await reasoner.generate(
                messages, images=None, tools=None,
                context={"purpose": "route", "response_format": ROUTE_SCHEMA,
                         "temperature": 0.0, "max_tokens": 160})
        except ModelUnavailable as exc:
            log.warning("router: model unavailable (%s)", exc.reason)
            return RouteDecision(available=False, failure=exc.reason, attempts=attempt)
        except Exception as exc:  # a flaky local server must not break the turn
            log.warning("router: model call failed: %s", type(exc).__name__)
            return RouteDecision(available=False, failure=type(exc).__name__, attempts=attempt)

        last_text = result.get("text") or ""
        parsed = validate(_extract_json(last_text))
        if parsed:
            log.info("router: intent=%s confidence=%.2f gate=%s (%s)", parsed["intent"],
                     parsed["confidence"], parsed["requires_safety_gate"], parsed["reason"])
            return RouteDecision(available=True, attempts=attempt, raw=parsed, **parsed)
        # One corrective retry, then give up honestly.
        messages = messages + [
            {"role": "assistant", "content": last_text[:400]},
            {"role": "user", "content": "That was not the required JSON object. Reply with "
                                        "only the JSON object, matching the schema exactly."},
        ]
    log.warning("router: model did not return the schema after %d attempts", max_attempts)
    return RouteDecision(available=False, failure="the model did not return a valid decision",
                         attempts=max_attempts)

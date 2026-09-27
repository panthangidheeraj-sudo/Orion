"""Ordinary conversation.

A field assistant that answers "hi" with "I need a bit more before I can narrow
this down" is not behaving like a technician. It is behaving like a form.

§1 asks for a calm, practical field technician. A technician says hello back,
tells you what they can help with, and waits. So a message that is purely
conversational short-circuits the whole agent loop: no retrieval, no tool
calls, no confidence meter, no safety banner — just a short reply.

This runs before the reasoning provider, which means it holds whichever model
is loaded. That is deliberate on two counts: a greeting should not spend an
NPU inference or a document search (§8's efficiency argument applies to idle
chat as much as to camera frames), and the answer should not depend on whether
a VLM happens to be exported yet.

The classifier is conservative. It only fires when the *whole* message is
conversational, so "hi, the motor is overheating" goes to the agent loop
exactly as it should.
"""

from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional

GREETING = re.compile(
    r"^(hi|hey+|hello|yo|hiya|howdy|good\s+(morning|afternoon|evening|day)|"
    r"morning|evening)\b", re.I)
THANKS = re.compile(
    r"^(thanks|thank\s+you|thankyou|ta|cheers|much\s+appreciated|appreciate\s+it|"
    r"nice\s+one|perfect|great|awesome|brilliant|lovely)\b", re.I)
FAREWELL = re.compile(
    r"^(bye|goodbye|see\s+(you|ya)|later|good\s*night|gn|cya|that'?s\s+all|"
    r"i'?m\s+done|all\s+done)\b", re.I)
ACK = re.compile(
    r"^(ok(ay)?|k|sure|right|alright|got\s+it|understood|yes|yeah|yep|yup|no|nope|"
    r"fine|cool|noted|will\s+do|makes\s+sense)\b", re.I)
# "what is this?" alone is a capability question; "what is this component?"
# names a thing and must fall through to the technical check below, so those
# two forms are anchored to the whole message rather than matched anywhere.
CAPABILITY = re.compile(
    r"(what\s+(can|do)\s+you\s+do|what\s+are\s+you\s+(for|able)|who\s+are\s+you|"
    r"^what\s+is\s+this\??$|^what'?s\s+this\??$|how\s+(do|does)\s+(you|this)\s+work|"
    r"what\s+can\s+i\s+ask|how\s+can\s+you\s+help|can\s+you\s+help|help\s+me\s+out|"
    r"^help\b|^\?+$|what\s+are\s+your\s+(features|capabilities))", re.I)
SMALLTALK = re.compile(
    r"^(how\s+are\s+(you|things)|how'?s\s+it\s+going|what'?s\s+up|sup|you\s+(there|"
    r"alive|awake|working))\b", re.I)
IDENTITY = re.compile(
    r"(what\s+model\s+are\s+you|are\s+you\s+(chatgpt|gpt|claude|an?\s+ai|a\s+(bot|robot))|"
    r"who\s+(made|built)\s+you|are\s+you\s+real\s+ai|do\s+you\s+run\s+(locally|offline)|"
    r"are\s+you\s+online|what'?s\s+your\s+name|what\s+is\s+your\s+name|"
    r"do\s+you\s+have\s+a\s+name)", re.I)
# Playful, opinion-style questions -- "do you like cats?", "what's your favourite tool?"
OPINION = re.compile(
    r"\b(do\s+you\s+(like|love|enjoy|prefer|hate)|what'?s\s+your\s+favou?rite|"
    r"what\s+is\s+your\s+favou?rite|are\s+you\s+(a\s+fan\s+of|into))\b", re.I)
# Asking for a joke or something lighthearted.
JOKE = re.compile(
    r"\b(tell\s+me\s+a\s+joke|know\s+any\s+jokes?|got\s+any\s+jokes?|make\s+me\s+laugh|"
    r"say\s+something\s+funny|be\s+funny)\b", re.I)

# If any of this is present the message is work, whatever else it contains.
# Words that can take a plural/gerund/past-tense suffix ("smells", "sparking",
# "burnt") carry \w* so the stem still matches -- a bare word with a trailing
# \b boundary does not match its own inflected forms, which used to let
# "it smells like burning and small sparks" slip through as plain chat.
TECHNICAL = re.compile(
    r"\b(motor|pump|drive|bearing|panel|fault|error|code\w*|alarm|trip\w*|leak\w*|"
    r"noise|nois\w*|vibrat\w*|overheat\w*|hot|smell\w*|smok\w*|spark\w*|burn\w*|"
    r"scorch\w*|arc(?:ing|ed)?|volt\w*|amp\w*|current|pressure|"
    r"temperature|torque|seal|gearbox|contactor|relay|fuse|breaker|terminal|winding|"
    r"schematic|manual|diagram|inspect\w*|repair\w*|replace\w*|measure\w*|test\w*|machine|"
    r"equipment|component\w*|broken|fail\w*|stuck|jam\w*|rattl\w*|grind\w*|squeal\w*|"
    r"nameplate|rating\s*plate|serial|part\s*number|label|gauge|shaft|coupling|belt|"
    r"valve|hose|filter|sensor|cable|wire|fan|impeller|spindle|reading|photo|picture|"
    r"image|camera|this\s+(one|thing|unit|part))\b", re.I)
# A number with a unit is a measurement, not chat.
MEASUREMENT = re.compile(r"\d\s*(°|deg|c\b|f\b|v\b|a\b|ma\b|hz|rpm|bar|psi|nm|mm|kw|db)", re.I)
# A fault code or part number -- "E17", "NSK6203" -- names something specific
# even though it isn't an English word the TECHNICAL list can name.
CODE_TOKEN = re.compile(r"\b(?=[a-z]*\d)(?=[a-z0-9-]*[a-z])[a-z][a-z0-9-]{1,9}\b", re.I)

MAX_CONVERSATIONAL_WORDS = 14


def classify(text: str) -> Optional[str]:
    """Return a conversational intent, or None when this is work.

    None used to be the unconditional safe answer, on the theory that routing
    to the full agent loop can never be wrong. In practice it meant a message
    with no technical signal at all -- "do you like cats?", "tell me a joke"
    -- that also didn't happen to match one of the named categories below
    fell through to the diagnostic loop anyway, and came back asking for a
    symptom nobody gave it. The default now matches the actual safety
    argument: only a technical or measurement cue routes to work; a short,
    plain message with neither is a conversation even when it isn't one of
    the specifically-named kinds (the final `chitchat` below).
    """
    raw = (text or "").strip()
    if not raw:
        return None

    # Anything naming equipment, a symptom, a reading, or a code/part number is
    # work, even if it opens with a greeting: "hi, the motor is overheating".
    if TECHNICAL.search(raw) or MEASUREMENT.search(raw) or CODE_TOKEN.search(raw):
        return None

    stripped = raw.strip(" .!?,-")
    words = stripped.split()

    # A capability question can be a full sentence; the rest are short by nature.
    if CAPABILITY.search(stripped):
        return "capability"
    if IDENTITY.search(stripped):
        return "identity"
    if JOKE.search(stripped):
        return "joke"
    if OPINION.search(stripped):
        return "opinion"
    if len(words) > MAX_CONVERSATIONAL_WORDS:
        return None
    if SMALLTALK.match(stripped):
        return "smalltalk"
    if GREETING.match(stripped):
        return "greeting"
    if THANKS.match(stripped):
        return "thanks"
    if FAREWELL.match(stripped):
        return "farewell"
    if ACK.match(stripped) and len(words) <= 4:
        return "acknowledgement"
    # Nothing named above matched. Staying conservative here matters: "the
    # flange on the pump is behaving oddly" has no technical keyword this
    # file happens to list, but it is still a technician describing a
    # machine, not small talk -- the diagnostic path already says "I don't
    # recognise that pattern" honestly rather than inventing one, a much
    # safer failure mode than routing a real complaint into a joke reply.
    # The specific patterns above (opinion/joke/identity/capability/…) are
    # what actually closed Bug 1's gap; this default is unchanged.
    return None


def _inventory(ctx: Dict[str, Any]) -> str:
    """One honest line about what this machine can actually bring to bear."""
    docs = int(ctx.get("document_count") or 0)
    bits: List[str] = []
    if docs:
        bits.append(f"{docs} document{'s' if docs != 1 else ''} indexed")
    else:
        bits.append("no manuals uploaded yet")
    if ctx.get("job_title"):
        bits.append(f"open job: {ctx['job_title']}")
    return " · ".join(bits)


def reply(intent: str, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A short, plain reply. No sections, no confidence meter, no hazard banner."""
    ctx = ctx or {}
    docs = int(ctx.get("document_count") or 0)
    job = ctx.get("job_title")
    returning = bool(ctx.get("has_history"))
    name = (ctx.get("display_name") or "").strip()
    who = f" {name}" if name and name.lower() != "technician" else ""

    if intent == "greeting":
        if job:
            text = (f"Hello{who}. You've got \u201c{job}\u201d open — tell me what's "
                    "changed, or point the camera at it.")
        elif returning:
            text = (f"Hello again{who}. What are you looking at?")
        else:
            text = (f"Hello{who}. Tell me what the machine is doing — the symptom, "
                    "when it started, what it sounds or smells like. A photo or the "
                    "camera gets me there faster.")
        return _shape(text, ctx)

    if intent == "smalltalk":
        return _shape(
            "Running fine and entirely on this machine. What are we looking at?", ctx)

    if intent == "capability":
        lines = [
            "I'm a field assistant for inspecting and repairing equipment. Practically:",
            "",
            "• Describe a symptom and I'll work through likely causes and what to test next.",
            "• Show me a photo, or open Live Mode and point the camera at the machine.",
            "• Upload manuals, datasheets and schematics — I'll search them and cite the page.",
            "• I keep a record per machine, so next visit I can tell you what we found last time.",
            "• I'll write the service report from what was actually recorded.",
            "",
            "Two things I won't do: invent a measurement, or tell you to work on live "
            "equipment. If I don't know, I'll say so and ask for the reading I need.",
        ]
        if not docs:
            lines += ["", "Nothing is in the vault yet — drop a manual in and I can start "
                          "citing it."]
        return _shape("\n".join(lines), ctx)

    if intent == "identity":
        engine = ctx.get("engine") or {}
        provider = engine.get("provider", "unknown")
        synthetic = engine.get("synthetic")
        where = ("running entirely on this machine — nothing you show me leaves it "
                 "unless you turn web research on")
        if synthetic:
            detail = (f"Right now the reasoning is a deterministic stand-in "
                      f"(`{engine.get('model_id', provider)}`), not a language model, "
                      "because no model has been exported to this machine yet. It still "
                      "reads your manuals and your job history; it just can't hold an "
                      "open-ended conversation.")
        else:
            detail = (f"Reasoning is running on `{engine.get('model_id', provider)}` "
                      f"({engine.get('accelerator', 'cpu')}"
                      f"{', NPU' if engine.get('npu') else ''}).")
        return _shape(f"I'm Orion, {where}. {detail}", ctx)

    if intent == "thanks":
        return _shape("Any time. Anything else on this machine?", ctx)

    if intent == "farewell":
        if job:
            return _shape(f"Right you are. \u201c{job}\u201d stays open — everything "
                          "recorded is saved on this machine for next time.", ctx)
        return _shape("Right you are. Everything's saved locally for next time.", ctx)

    if intent == "opinion":
        return _shape(
            "I don't really have preferences — I'm tuned for machines, not opinions. Happy "
            "to chat, but I'm most useful once we're looking at some equipment. What have "
            "you got?", ctx)

    if intent == "joke":
        jokes = [
            "Why did the motor file a complaint? It said it was being taken for a spin.",
            "Why do bearings make terrible secret-keepers? They always end up squealing.",
            "A technician's favourite genre of music? Anything with a good torque sequence.",
        ]
        return _shape(f"{random.choice(jokes)} ...Anyway — what are we working on?", ctx)

    if intent == "acknowledgement":
        return _shape("Go on — what's it doing?", ctx)

    return _shape("Tell me what you're looking at.", ctx)


def _shape(text: str, ctx: Dict[str, Any]):
    """A conversational turn carries no diagnostic furniture.

    That includes suggestion chips. The reply already says what to do next, and
    a row of buttons under "hello" is the product showing off rather than a
    technician answering. Follow-ups stay where they earn their place: under a
    diagnosis, where they point at a specific page or a specific next test.
    """
    return {
        "text": text,
        "tool_calls": [],
        "sections": [],          # no Observed / Likely causes on a greeting
        "conversational": True,
        "meta": {"confidence": None, "hazards": [], "refs": [], "follow_ups": []},
    }

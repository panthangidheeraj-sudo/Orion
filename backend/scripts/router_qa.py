#!/usr/bin/env python3
"""How does YOUR model route real messages?

    python scripts/router_qa.py [base_url]

Runs the router QA set and the multi-turn transitions against a running
backend and prints what the model decided for each. There is no special-case
code behind any of these messages — every decision below comes from the
configured reasoning model. Start a local model first (see README: "Running a
local model"); without one every line reads `fallback`, which is correct.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8756").rstrip("/")
KEY = os.environ.get("VF_ACCESS_TOKEN", "")
client = httpx.Client(base_url=BASE, timeout=180.0,
                      headers={"X-Orion-Key": KEY} if KEY else None)

# (message, what a good router should decide)
SINGLE: List[Tuple[str, str]] = [
    ("hellooo", "conversation"),
    ("do you like cats?", "conversation"),
    ("hmm", "conversation"),
    ("what do you think?", "conversation"),
    ("tell me something interesting", "conversation"),
    ("why are you called Orion?", "conversation"),
    ("something's wrong", "ambiguous"),
    ("it isn't working", "ambiguous"),
    ("can you help?", "ambiguous"),
    ("my motor is vibrating", "technical"),
    ("the breaker trips after a few minutes", "technical"),
    ("there are sparks from the panel", "technical"),
    ("what torque does this manual specify?", "technical"),
]

TRANSITIONS: List[List[Tuple[str, str]]] = [
    [("My motor is vibrating.", "technical"), ("yeah, exactly.", "technical")],
    [("Do you like cats?", "conversation"), ("Anyway, my pump is leaking.", "technical")],
    [("the breaker keeps tripping", "technical"), ("haha thanks, you're a lifesaver", "conversation"),
     ("ok back to it — it trips as soon as the pump starts", "technical")],
]


def ask(message: str, cid: Optional[str] = None, **kw) -> Dict[str, Any]:
    body = {"message": message, **kw}
    if cid:
        body["conversation_id"] = cid
    r = client.post("/api/chat", json=body)
    r.raise_for_status()
    return r.json()


def line(message: str, want: str, r: Dict[str, Any]) -> bool:
    got = r.get("intent") or "—"
    ok = got == want or (want == "ambiguous" and r.get("kind") == "clarify")
    conf = (r.get("route") or {}).get("confidence")
    mark = "ok " if ok else "DIFF"
    notice = " [safety notice]" if (r.get("notice") or {}).get("level") == "safety" else ""
    print(f"  {mark} {message[:44]:<44} → {r.get('kind'):<12} intent={got:<12} "
          f"conf={conf}{notice}")
    print(f"       {r.get('text', '')[:110]!r}")
    return ok


def main() -> int:
    status = client.get("/api/models/status").json()["roles"]["reasoning"]
    print(f"reasoning: {status['provider']} / {status['model_id']} — {status['status']}"
          + (f" ({status.get('reason')})" if status["status"] != "ready" else ""))

    agree = total = 0
    print("\nSingle messages")
    for message, want in SINGLE:
        total += 1
        agree += line(message, want, ask(message))

    print("\nWith an attachment")
    for message, att, want in [("summarize this", {"kind": "pdf", "name": "manual.pdf"}, "conversation"),
                               ("what torque should I use?", {"kind": "pdf", "name": "manual.pdf"},
                                "technical")]:
        total += 1
        agree += line(f"{message} [+{att['kind']}]", want, ask(message, attachments=[att]))

    print("\nMulti-turn")
    for convo in TRANSITIONS:
        cid = None
        for message, want in convo:
            r = ask(message, cid)
            cid = r["conversation_id"]
            total += 1
            agree += line(message, want, r)
        print()

    print(f"{agree}/{total} decisions matched the expected intent.")
    print("A DIFF is a model decision to look at, not necessarily a bug — judge the reply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

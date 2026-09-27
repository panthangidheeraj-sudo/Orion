"""A scripted stand-in for a real local language model — TESTS ONLY.

The app never imports this. It lets the suite drive the router and the agent
loop deterministically: each test says what "the model" answers for routing,
for conversation and for technical turns, and then checks what the pipeline
did with that answer. Whether a real model routes "do you like cats?"
correctly is a property of the model, checked with scripts/router_qa.py
against the user's own model server — not something a unit test can fake.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

from app.models.base import READY, ModelHealth, ReasoningProvider

RouteFn = Callable[[str, str], Any]           # (latest message, full router prompt) -> dict | str
ChatFn = Callable[[List[Dict[str, Any]], Dict[str, Any]], str]
TechFn = Callable[[List[Dict[str, Any]], Any, Any, Dict[str, Any]], Dict[str, Any]]


def latest_message(prompt: str) -> str:
    m = re.search(r"Latest message:\n(.*?)\n\nReturn the JSON object now\.", prompt, re.S)
    return m.group(1) if m else ""


def decision(intent: str, confidence: float = 0.9, gate: bool = False,
             reason: str = "scripted") -> Dict[str, Any]:
    return {"intent": intent, "confidence": confidence, "reason": reason,
            "requires_safety_gate": gate}


def default_technical(messages, images, tools, ctx) -> Dict[str, Any]:
    evidence = ctx.get("evidence") or {}
    user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    lines = ["Observed"]
    for r in ((evidence.get("search_documents") or {}).get("results") or [])[:1]:
        lines.append(f"- {r['filename']} page {r['page_start']} says: {r['content'][:500]}")
    for f in ((evidence.get("get_job_history") or {}).get("findings") or [])[:2]:
        lines.append(f"- Last visit: {f['description']}")
    if len(lines) == 1:
        lines.append("- Nothing has been measured or seen yet.")
    lines += ["Likely causes", "- Unknown — it needs a reading to narrow down",
              "What to test next", f"- Start from what was reported: {user[:80]}"]
    return {"text": "\n".join(lines), "tool_calls": []}


class ScriptedLLM(ReasoningProvider):
    def __init__(self, route: Optional[RouteFn] = None, chat: Optional[ChatFn] = None,
                 technical: Optional[TechFn] = None) -> None:
        super().__init__("scripted-test-model", "test-double")
        self.route_fn = route or (lambda msg, prompt: decision("technical"))
        self.chat_fn = chat or (lambda messages, ctx: "Happy to chat.")
        self.technical_fn = technical or default_technical
        self.calls: List[Dict[str, Any]] = []

    def _load(self) -> None:
        self._health = ModelHealth(role=self.role, provider=self.provider,
                                   model_id=self.model_id, status=READY,
                                   runtime="test", accelerator="cpu")

    @property
    def route_calls(self) -> List[Dict[str, Any]]:
        return [c for c in self.calls if c["purpose"] == "route"]

    async def generate(self, messages, images=None, tools=None, context=None) -> Dict[str, Any]:
        ctx = dict(context or {})
        purpose = ctx.get("purpose")
        self.calls.append({"purpose": purpose, "messages": [dict(m) for m in messages],
                           "images": list(images or []), "tools": list(tools or []),
                           "context": ctx})
        if purpose == "route":
            prompt = messages[-1]["content"]
            out = self.route_fn(latest_message(prompt), prompt)
            return {"text": out if isinstance(out, str) else json.dumps(out), "tool_calls": []}
        if purpose in ("conversation", "ambiguous"):
            return {"text": self.chat_fn(messages, ctx), "tool_calls": []}
        return self.technical_fn(messages, images, tools, ctx)

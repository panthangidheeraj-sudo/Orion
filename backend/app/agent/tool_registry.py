"""Tool registry (§15).

Every tool is declared with a JSON-schema parameter block and a handler, and
every invocation goes through :meth:`ToolRegistry.call`, which

* refuses any name that is not registered — the allowlist is the registry
  itself, and an unknown name never reaches a handler;
* validates arguments against the declared schema before the handler runs;
* enforces a timeout;
* times the call and returns structured JSON with ``ok``, ``tool``,
  ``duration_ms`` and ``source``;
* converts an exception into the §25 error envelope instead of propagating it,
  so one failing sense never takes down the answer;
* logs failures without exposing arguments or results verbatim.

There is deliberately no shell tool, no filesystem tool and no "eval" tool.
§15: the agent must not execute arbitrary shell commands or access arbitrary
filesystem paths.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from app.config import settings
from app.errors import ToolError, ToolNotAllowed, VFError, ValidationFailed
from app.logging_setup import get_logger
from app.util import timed

log = get_logger(__name__)

Handler = Callable[..., Awaitable[Dict[str, Any]]]

TYPES = {"string": str, "number": (int, float), "integer": int,
         "boolean": bool, "array": list, "object": dict}


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Handler
    category: str = "general"
    online: bool = False           # touches the network
    mutates: bool = False          # writes to the local store
    needs_roles: List[str] = field(default_factory=list)

    def schema(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "parameters": self.parameters, "category": self.category,
                "online": self.online, "mutates": self.mutates}


def validate(args: Dict[str, Any], schema: Dict[str, Any], tool: str) -> Dict[str, Any]:
    """Minimal JSON-schema check: types, required, enum, bounds, defaults."""
    props: Dict[str, Any] = schema.get("properties", {}) or {}
    required: Sequence[str] = schema.get("required", []) or []
    if not isinstance(args, dict):
        raise ValidationFailed(f"{tool}: arguments must be an object", tool=tool)

    unknown = [k for k in args if k not in props]
    if unknown and schema.get("additionalProperties") is False:
        raise ValidationFailed(f"{tool}: unexpected argument(s) {', '.join(sorted(unknown))}",
                               tool=tool, accepted=sorted(props))

    clean: Dict[str, Any] = {}
    for key, spec in props.items():
        if key not in args or args[key] is None:
            if key in required:
                raise ValidationFailed(f"{tool}: '{key}' is required", tool=tool)
            if "default" in spec:
                clean[key] = spec["default"]
            continue
        value = args[key]
        expected = spec.get("type")
        if expected and expected in TYPES and not isinstance(value, TYPES[expected]):
            if expected == "number" and isinstance(value, bool):
                raise ValidationFailed(f"{tool}: '{key}' must be a number", tool=tool)
            if expected in ("number", "integer") and isinstance(value, str):
                try:
                    value = float(value) if expected == "number" else int(value)
                except ValueError:
                    raise ValidationFailed(f"{tool}: '{key}' must be {expected}", tool=tool)
            else:
                raise ValidationFailed(
                    f"{tool}: '{key}' must be {expected}, got {type(value).__name__}", tool=tool)
        if "enum" in spec and value not in spec["enum"]:
            raise ValidationFailed(f"{tool}: '{key}' must be one of {spec['enum']}", tool=tool)
        if isinstance(value, str):
            if "maxLength" in spec:
                value = value[: spec["maxLength"]]
            if spec.get("minLength") and len(value) < spec["minLength"]:
                raise ValidationFailed(f"{tool}: '{key}' is too short", tool=tool)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in spec and value < spec["minimum"]:
                raise ValidationFailed(f"{tool}: '{key}' must be >= {spec['minimum']}", tool=tool)
            if "maximum" in spec and value > spec["maximum"]:
                raise ValidationFailed(f"{tool}: '{key}' must be <= {spec['maximum']}", tool=tool)
        clean[key] = value
    return clean


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise RuntimeError(f"tool '{spec.name}' is already registered")
        self._tools[spec.name] = spec

    def tool(self, name: str, description: str, parameters: Dict[str, Any], **kw):
        def deco(fn: Handler) -> Handler:
            self.register(ToolSpec(name=name, description=description,
                                   parameters=parameters, handler=fn, **kw))
            return fn
        return deco

    def get(self, name: str) -> ToolSpec:
        spec = self._tools.get(name)
        if spec is None:
            raise ToolNotAllowed(
                f"'{name}' is not a registered tool", tool=name,
                allowed=sorted(self._tools))
        return spec

    def names(self) -> List[str]:
        return sorted(self._tools)

    def schemas(self, allow: Optional[Sequence[str]] = None,
                online_allowed: bool = False) -> List[Dict[str, Any]]:
        out = []
        for name, spec in sorted(self._tools.items()):
            if allow is not None and name not in allow:
                continue
            if spec.online and not online_allowed:
                continue
            out.append(spec.schema())
        return out

    async def call(self, name: str, arguments: Optional[Dict[str, Any]] = None,
                   context: Optional[Dict[str, Any]] = None,
                   allow: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        arguments = dict(arguments or {})
        if allow is not None and name not in allow:
            err = ToolNotAllowed(f"'{name}' is not permitted in this context", tool=name)
            return {"ok": False, "tool": name, "duration_ms": 0.0, **err.to_dict()}
        try:
            spec = self.get(name)
        except VFError as exc:
            return {"ok": False, "tool": name, "duration_ms": 0.0, **exc.to_dict()}

        try:
            clean = validate(arguments, spec.parameters, name)
        except VFError as exc:
            return {"ok": False, "tool": name, "duration_ms": 0.0, **exc.to_dict()}

        kwargs = dict(clean)
        if "context" in inspect.signature(spec.handler).parameters:
            kwargs["context"] = context or {}

        with timed() as t:
            try:
                result = await asyncio.wait_for(spec.handler(**kwargs),
                                                timeout=settings.agent_tool_timeout_s)
                ok, payload = True, (result if isinstance(result, dict) else {"value": result})
            except asyncio.TimeoutError:
                log.warning("tool %s timed out after %.1fs", name, settings.agent_tool_timeout_s)
                ok, payload = False, ToolError(
                    f"timed out after {settings.agent_tool_timeout_s:.0f}s", tool=name).to_dict()
            except VFError as exc:
                log.info("tool %s returned a structured error: %s", name, exc.code)
                ok, payload = False, exc.to_dict()
            except Exception as exc:
                log.warning("tool %s failed: %s", name, type(exc).__name__)
                ok, payload = False, ToolError(
                    f"{type(exc).__name__}: {exc}", tool=name).to_dict()

        return {"ok": ok, "tool": name, "category": spec.category,
                "duration_ms": t["ms"], "source": payload.pop("source", spec.category), **payload}


registry = ToolRegistry()

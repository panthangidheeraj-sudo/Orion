"""Memory tools (§13, §15).

Reads are free; writes go through the §13 policy in the memory service, so a
tool call cannot store a guess just because the model asked it to.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agent.tool_registry import registry as tools
from app.knowledge.retrieval import search_memories
from app.memory import memory_service as M
from app.memory.schemas import MEMORY_TYPES


@tools.tool(
    "search_memory",
    "Search durable local memory: confirmed machine identities, measurements, "
    "faults, repair actions and results from earlier work.",
    {"type": "object", "additionalProperties": False,
     "required": ["query"],
     "properties": {"query": {"type": "string", "minLength": 2, "maxLength": 300},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 12, "default": 6},
                    "job_id": {"type": "string", "maxLength": 64}}},
    category="memory")
async def search_memory(query: str, top_k: int = 6, job_id: Optional[str] = None):
    rows = await search_memories(query, top_k=top_k, job_id=job_id)
    return {"memories": rows, "count": len(rows), "source": "local_memory"}


@tools.tool(
    "get_job_history",
    "Retrieve everything recorded for a job: the machine, past inspections, "
    "findings, measurements and durable memories.",
    {"type": "object", "additionalProperties": False,
     "required": ["job_id"],
     "properties": {"job_id": {"type": "string", "maxLength": 64}}},
    category="memory")
async def get_job_history(job_id: str):
    return {**M.job_history(job_id), "source": "local_memory"}


@tools.tool(
    "save_memory",
    "Store a confirmed fact durably. Only confirmed machine identities, "
    "measurements, faults, repair actions, results, approved preferences and "
    "document associations are accepted; speculation is refused.",
    {"type": "object", "additionalProperties": False,
     "required": ["memory_type", "content"],
     "properties": {
         "memory_type": {"type": "string", "enum": list(MEMORY_TYPES)},
         "content": {"type": "string", "minLength": 8, "maxLength": 1200},
         "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
         "confirmed": {"type": "boolean", "default": False,
                       "description": "True only when the technician confirmed it."},
         "job_id": {"type": "string", "maxLength": 64},
     }},
    category="memory", mutates=True)
async def save_memory(memory_type: str, content: str, confidence: Optional[float] = None,
                      confirmed: bool = False, job_id: Optional[str] = None,
                      context: Dict[str, Any] = None):
    context = context or {}
    result = await M.save_memory(
        memory_type=memory_type, content=content, confidence=confidence,
        source={"origin": "agent_tool", "conversation_id": context.get("conversation_id"),
                "inspection_id": context.get("inspection_id")},
        job_id=job_id or context.get("job_id"), confirmed=confirmed)
    return {**result, "source": "local_memory"}


@tools.tool(
    "save_finding",
    "Record an observation or diagnosis against the current inspection.",
    {"type": "object", "additionalProperties": False,
     "required": ["description"],
     "properties": {
         "description": {"type": "string", "minLength": 6, "maxLength": 1200},
         "type": {"type": "string", "maxLength": 60,
                  "description": "observation | fault | repair | result"},
         "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
         "inspection_id": {"type": "string", "maxLength": 64},
     }},
    category="memory", mutates=True)
async def save_finding(description: str, type: Optional[str] = None,
                       confidence: Optional[float] = None,
                       inspection_id: Optional[str] = None, context: Dict[str, Any] = None):
    context = context or {}
    iid = inspection_id or context.get("inspection_id")
    if not iid:
        return {"saved": False,
                "reason": "no active inspection; start one before recording findings"}
    row = M.save_finding(iid, description, type=type, confidence=confidence,
                         source={"origin": "agent_tool",
                                 "conversation_id": context.get("conversation_id")})
    return {"saved": True, "finding": row, "source": "local_memory"}


@tools.tool(
    "save_measurement",
    "Record a measurement the technician actually took. A value is mandatory — "
    "measurements are never estimated or inferred.",
    {"type": "object", "additionalProperties": False,
     "required": ["name", "value"],
     "properties": {
         "name": {"type": "string", "minLength": 2, "maxLength": 80},
         "value": {"type": "number"},
         "unit": {"type": "string", "maxLength": 16},
         "source": {"type": "string", "maxLength": 40, "default": "technician"},
         "inspection_id": {"type": "string", "maxLength": 64},
     }},
    category="memory", mutates=True)
async def save_measurement(name: str, value: float, unit: Optional[str] = None,
                           source: str = "technician", inspection_id: Optional[str] = None,
                           context: Dict[str, Any] = None):
    context = context or {}
    iid = inspection_id or context.get("inspection_id")
    if not iid:
        return {"saved": False,
                "reason": "no active inspection; start one before recording measurements"}
    row = M.save_measurement(iid, name, value, unit=unit, source=source)
    return {"saved": True, "measurement": row, "source": "local_memory"}

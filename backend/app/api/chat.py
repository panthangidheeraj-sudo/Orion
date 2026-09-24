"""Chat endpoints (§20): /api/chat, /api/chat/stream, /api/conversations."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.agent.orchestrator import orchestrator
from app.agent.tool_registry import registry as tool_registry
from app.logging_setup import get_logger
from app.memory import memory_service as M
from app.schemas.chat import ChatRequest, ChatResponse, ConversationCreate
from app.schemas.tools import ToolCallRequest

log = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> Dict[str, Any]:
    """Ask the agent. The backend runs the whole loop and returns a finished answer."""
    return await orchestrator.ask(
        req.message, conversation_id=req.conversation_id, image_ids=req.image_ids,
        job_id=req.job_id, inspection_id=req.inspection_id, mode=req.mode,
        web=req.web, profile=req.profile, allow_writes=req.allow_writes)


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    """Server-sent events: the work trail arrives before the answer."""

    async def gen():
        try:
            async for event in orchestrator.stream(
                req.message, conversation_id=req.conversation_id, image_ids=req.image_ids,
                job_id=req.job_id, inspection_id=req.inspection_id, mode=req.mode,
                web=req.web, profile=req.profile, allow_writes=req.allow_writes,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:  # the stream must close cleanly, always
            log.warning("stream failed: %s", type(exc).__name__)
            yield "data: " + json.dumps(
                {"type": "error", "error": "STREAM_FAILED",
                 "reason": f"{type(exc).__name__}"}) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.get("/conversations")
async def list_conversations(limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    rows = M.list_conversations(limit)
    return {"conversations": rows, "count": len(rows)}


@router.post("/conversations")
async def create_conversation(req: ConversationCreate) -> Dict[str, Any]:
    return M.create_conversation(req.title)


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str) -> Dict[str, Any]:
    conv = M.get_conversation(conversation_id)
    return {**conv, "messages": M.get_messages(conversation_id, limit=200)}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str) -> Dict[str, Any]:
    return M.delete_conversation(conversation_id)


@router.get("/tools")
async def list_tools() -> Dict[str, Any]:
    """The tool allowlist, as the agent sees it (§15)."""
    schemas = tool_registry.schemas(online_allowed=True)
    return {"tools": schemas, "count": len(schemas),
            "note": "This registry is the allowlist. There is no shell, filesystem or "
                    "code-execution tool by design."}


@router.post("/tools/call")
async def call_tool(req: ToolCallRequest) -> Dict[str, Any]:
    """Invoke one tool directly — used by the UI for explicit actions."""
    result = await tool_registry.call(
        req.tool, req.arguments,
        context={"conversation_id": req.conversation_id,
                 "inspection_id": req.inspection_id, "job_id": req.job_id})
    if req.conversation_id:
        M.log_tool_call(req.conversation_id, req.tool, req.arguments, result,
                        result.get("duration_ms", 0.0))
    return result

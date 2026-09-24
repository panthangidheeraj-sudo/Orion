"""Importing this package registers every tool with the agent's registry."""

from app.tools import (  # noqa: F401
    document_tools, memory_tools, report_tools, vision_tools, web_tools,
)

__all__ = ["document_tools", "memory_tools", "report_tools", "vision_tools", "web_tools"]

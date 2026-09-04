from __future__ import annotations

import logging
import re
from typing import Any

from crabagent.core.mcp.client import MCPClientManager


def _sanitize(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


logger = logging.getLogger(__name__)

# These tools analyze an image that already exists. A vision-capable model can
# inspect the same file via the built-in read tool, avoiding an unnecessary MCP
# dependency. Specialized UI, OCR, diagram, chart, comparison, and video tools
# remain available because they provide workflows beyond direct image viewing.
_GENERIC_IMAGE_ANALYSIS_TOOLS = frozenset({"analyze_image"})


def direct_vision_redundant_tool_names(registry) -> set[str]:
    """Return MCP tools that duplicate native image inspection."""
    return {
        tool.name
        for tool in registry.list_tools()
        if tool.metadata.get("source") == "mcp"
        and str(tool.metadata.get("original_tool_name", "")).lower() in _GENERIC_IMAGE_ANALYSIS_TOOLS
    }


def register_mcp_tools(registry, manager: MCPClientManager) -> None:
    connections = manager.get_all_connections()
    for server_name, conn in connections.items():
        if not conn.is_connected:
            continue
        config = conn.config
        for mcp_tool in conn._tools:
            _register_single_tool(registry, manager, config, mcp_tool)


def _register_single_tool(registry, manager: MCPClientManager, config, mcp_tool) -> None:
    tool_name = f"mcp__{_sanitize(config.name)}__{_sanitize(mcp_tool.name)}"

    existing = registry.get(tool_name)
    if existing:
        return

    server_meta = {
        "source": "mcp",
        "server_name": config.name,
        "server_display_name": config.display_name or config.name,
        "original_tool_name": mcp_tool.name,
    }

    description = f"[MCP: {config.display_name or config.name}] {mcp_tool.description}"

    registry.register(
        name=tool_name,
        description=description,
        parameters=mcp_tool.input_schema,
        requires_permission=False,
        metadata=server_meta,
    )(_make_mcp_handler(manager, config.name, mcp_tool.name, tool_name))

    logger.debug("Registered MCP tool '%s' from server '%s'", tool_name, config.name)


def _make_mcp_handler(manager: MCPClientManager, server_name: str, original_name: str, tool_name: str):
    async def handler(**kwargs: Any) -> object:
        conn = manager.get_connection(server_name)
        if not conn or not conn.is_connected:
            return f"Error: MCP server '{server_name}' is not connected"
        try:
            return await conn.call_tool(original_name, kwargs)
        except Exception as e:
            return f"Error calling MCP tool '{tool_name}': {e}"

    return handler

from __future__ import annotations

from crabagent.core.agent.agents import get_delegation_tools, get_memory_tools, get_shared_tools
from crabagent.core.agent.tools.registry import ToolRegistry

_ALWAYS_BLOCKED = {
    "delegate_task",
    "delegate_parallel",
    "list_agents",
    "handoff_to",
    "create_tool",
    "update_tool",
    "delete_tool",
}


def filter_tool_registry(full_registry: ToolRegistry, agent_tools: list[str] | None) -> ToolRegistry:
    filtered = ToolRegistry()
    allowed = set(agent_tools or []) | get_shared_tools() | get_memory_tools()
    blocked = get_delegation_tools() | _ALWAYS_BLOCKED

    for name, tool in full_registry._tools.items():
        if name in blocked:
            continue
        if name in allowed:
            filtered._tools[name] = tool

    return filtered

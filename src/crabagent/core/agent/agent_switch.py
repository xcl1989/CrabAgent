from __future__ import annotations

from crabagent.core.agent.agents import get_delegation_tools, get_memory_tools
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


def filter_tool_registry(
    full_registry: ToolRegistry,
    agent_tools: list[str] | None = None,
    tool_permissions: dict[str, str] | None = None,
) -> ToolRegistry:
    filtered = ToolRegistry()
    blocked = get_delegation_tools() | _ALWAYS_BLOCKED
    allowed = set(agent_tools or [])
    use_whitelist = bool(agent_tools)

    for name, tool in full_registry._tools.items():
        if name in blocked:
            continue
        if name in get_memory_tools():
            filtered._tools[name] = tool
            continue
        if tool_permissions and tool_permissions.get(name) == "deny":
            continue
        if use_whitelist and name not in allowed:
            continue
        filtered._tools[name] = tool

    return filtered

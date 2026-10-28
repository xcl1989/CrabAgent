from __future__ import annotations

from crabagent.core.agent.agents import get_delegation_tools, get_memory_tools
from crabagent.core.agent.tools.registry import ToolRegistry

# Tools a *sub-agent* may never call: delegation plumbing (to avoid unbounded
# recursion) plus tool self-modification. The main agent legitimately needs
# delegation and tool creation, so it opts out via ``allow_delegation=True``.
_SUB_AGENT_BLOCKED = {
    "create_tool",
    "update_tool",
    "delete_tool",
}


def filter_tool_registry(
    full_registry: ToolRegistry,
    agent_tools: list[str] | None = None,
    tool_permissions: dict[str, str] | None = None,
    allow_delegation: bool = False,
) -> ToolRegistry:
    """Return a narrowed copy of ``full_registry`` for one agent profile.

    Args:
        full_registry: Source pool to copy from. Never mutated.
        agent_tools: Optional whitelist. When non-empty only these tools survive.
        tool_permissions: ``{tool_name: "auto"|"confirm"|"deny"}``; ``deny`` drops
            the tool entirely so it never reaches the model.
        allow_delegation: Set ``True`` for the main agent so delegation tools
            (``delegate_task``, ``list_agents``, ``ask_question``, ...) and tool
            self-management stay available. Sub-agents keep the default ``False``.
    """
    filtered = ToolRegistry()
    blocked: set[str] = set()
    if not allow_delegation:
        blocked = _SUB_AGENT_BLOCKED | get_delegation_tools()

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

"""Regression tests for agent-profile tool narrowing.

Two bugs are covered:

* ``filter_tool_registry`` used to strip delegation tools from the *main* agent,
  so switching to any non-default profile silently removed ``delegate_task``,
  ``list_agents``, ``handoff_to`` and ``ask_question``.
* ``spawn_sub_agent`` derived its tool pool from the parent's already-narrowed
  registry, so a parent profile's ``deny`` list leaked into every delegated
  sub-agent (e.g. coder denies ``browser`` -> researcher never got it either).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import crabagent.core.agent.agents as agents_module
from crabagent.core.agent.agent_switch import filter_tool_registry
from crabagent.core.agent.agents import get_delegation_tools
from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.tools.registry import ToolRegistry

ALL_TOOLS = [
    "bash",
    "read",
    "write",
    "edit",
    "glob",
    "grep",
    "web_search",
    "web_scrape",
    "browser",
    "shared_get",
    "shared_put",
    "shared_list",
    "delegate_task",
    "delegate_parallel",
    "list_agents",
    "handoff_to",
    "ask_question",
    "request_help",
    "create_tool",
]


def _registry(names: list[str] | None = None) -> ToolRegistry:
    reg = ToolRegistry()
    for name in names or ALL_TOOLS:
        reg.register(name, f"{name} tool", {})(lambda **kwargs: None)
    return reg


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


class TestFilterToolRegistry:
    def test_sub_agent_scope_still_blocks_delegation(self):
        """Default behaviour (sub-agent) must not change: no delegation plumbing."""
        filtered = filter_tool_registry(_registry())
        assert not (get_delegation_tools() & set(filtered._tools))
        assert "create_tool" not in filtered._tools

    def test_main_agent_keeps_delegation_tools(self):
        """Regression: the main agent must keep the ability to delegate and ask."""
        filtered = filter_tool_registry(_registry(), allow_delegation=True)
        names = set(filtered._tools)
        assert get_delegation_tools() <= names
        assert "create_tool" in names

    def test_main_agent_keeps_delegation_while_honouring_deny(self):
        filtered = filter_tool_registry(
            _registry(),
            tool_permissions={"browser": "deny", "bash": "auto"},
            allow_delegation=True,
        )
        names = set(filtered._tools)
        assert "delegate_task" in names
        assert "ask_question" in names
        assert "browser" not in names
        assert "bash" in names

    def test_source_registry_is_not_mutated(self):
        source = _registry()
        before = set(source._tools)
        filter_tool_registry(source, tool_permissions={"browser": "deny"}, allow_delegation=True)
        assert set(source._tools) == before


class TestSubAgentInheritsUnprunedPool:
    @pytest.mark.asyncio
    async def test_sub_agent_gets_tool_denied_by_parent_profile(self, monkeypatch: pytest.MonkeyPatch):
        researcher = {
            "name": "researcher",
            "display_name": "Web Researcher",
            "role": "Research",
            "goal": "Find facts",
            "backstory": "",
            "model": "",
            "allow_delegation": False,
            # researcher itself does not deny browser
            "tool_permissions": {"bash": "deny", "write": "deny", "edit": "deny"},
        }
        monkeypatch.setattr(agents_module, "get_agent", _async_return(researcher))
        monkeypatch.setattr(agents_module, "_classify_task", lambda task: "research")
        monkeypatch.setattr(agents_module, "inject_agent_lessons", _async_return("prompt"))
        monkeypatch.setattr(agents_module, "_load_shared_context", _async_return(""))

        captured: dict[str, set[str]] = {}

        async def fake_run_agent(context, query):
            captured["tools"] = set(context.tool_registry._tools)
            context.messages.append({"role": "assistant", "content": "done"})
            return context.messages

        monkeypatch.setattr("crabagent.core.agent.loop.run_agent", fake_run_agent)

        full = _registry()
        # Parent (coder) narrowed its own view: browser denied by coder's profile.
        narrowed = filter_tool_registry(full, tool_permissions={"browser": "deny"}, allow_delegation=True)
        parent = AgentContext(workspace=Path.cwd(), tool_registry=narrowed)
        parent.base_tool_registry = full
        assert "browser" not in parent.tool_registry._tools

        await agents_module.spawn_sub_agent("researcher", "look at the page", parent)

        assert "browser" in captured["tools"], "parent deny leaked into sub-agent"
        # Sub-agent still honours its OWN deny list.
        assert "bash" not in captured["tools"]
        assert "write" not in captured["tools"]

    @pytest.mark.asyncio
    async def test_falls_back_to_parent_registry_without_base(self, monkeypatch: pytest.MonkeyPatch):
        """When no base pool is set, behaviour must stay backward compatible."""
        coder = {
            "name": "coder",
            "display_name": "Code Expert",
            "role": "Code",
            "goal": "Ship",
            "backstory": "",
            "model": "",
            "allow_delegation": False,
            "tool_permissions": {},
        }
        monkeypatch.setattr(agents_module, "get_agent", _async_return(coder))
        monkeypatch.setattr(agents_module, "_classify_task", lambda task: "code")
        monkeypatch.setattr(agents_module, "inject_agent_lessons", _async_return("prompt"))
        monkeypatch.setattr(agents_module, "_load_shared_context", _async_return(""))

        captured: dict[str, set[str]] = {}

        async def fake_run_agent(context, query):
            captured["tools"] = set(context.tool_registry._tools)
            context.messages.append({"role": "assistant", "content": "done"})
            return context.messages

        monkeypatch.setattr("crabagent.core.agent.loop.run_agent", fake_run_agent)

        parent = AgentContext(workspace=Path.cwd(), tool_registry=_registry(["bash", "read"]))
        await agents_module.spawn_sub_agent("coder", "do it", parent)

        assert captured["tools"] == {"bash", "read"}

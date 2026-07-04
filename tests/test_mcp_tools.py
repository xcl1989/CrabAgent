"""Tests for MCP tool registration."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from crabagent.core.agent.tools.registry import ToolRegistry
from crabagent.core.mcp import tools as mcp_tools


class FakeMcpTool:
    def __init__(self, name, description, input_schema=None):
        self.name = name
        self.description = description
        self.input_schema = input_schema or {"type": "object", "properties": {}}


class FakeConn:
    def __init__(self, tools, connected=True):
        self.is_connected = connected
        self._tools = tools
        self.config = SimpleNamespace(name="test_server", display_name="Test Server")

    async def call_tool(self, name, kwargs):
        return f"called {name} with {kwargs}"


class FakeManager:
    def __init__(self, connections=None):
        self._connections = connections or {}

    def get_all_connections(self):
        return self._connections

    def get_connection(self, name):
        return self._connections.get(name)


def test_sanitize_replaces_special_chars():
    assert mcp_tools._sanitize("hello world!") == "hello_world_"
    assert mcp_tools._sanitize("a.b.c") == "a_b_c"
    assert mcp_tools._sanitize("ok-name_123") == "ok-name_123"


def test_register_mcp_tools_skips_disconnected():
    registry = ToolRegistry()
    conn = FakeConn([FakeMcpTool("tool1", "desc")], connected=False)
    manager = FakeManager({"test_server": conn})

    mcp_tools.register_mcp_tools(registry, manager)

    assert registry.get("mcp__test_server__tool1") is None


def test_register_mcp_tools_registers_connected():
    registry = ToolRegistry()
    conn = FakeConn([FakeMcpTool("tool1", "first tool"), FakeMcpTool("tool2", "second tool")])
    manager = FakeManager({"test_server": conn})

    mcp_tools.register_mcp_tools(registry, manager)

    t1 = registry.get("mcp__test_server__tool1")
    assert t1 is not None
    assert "[MCP: Test Server]" in t1.description

    t2 = registry.get("mcp__test_server__tool2")
    assert t2 is not None


def test_register_mcp_tools_skips_duplicate():
    registry = ToolRegistry()
    conn = FakeConn([FakeMcpTool("tool1", "desc")])
    manager = FakeManager({"test_server": conn})

    mcp_tools.register_mcp_tools(registry, manager)
    mcp_tools.register_mcp_tools(registry, manager)  # second time

    assert len(registry.list_tools()) == 1


def test_register_mcp_tools_with_multiple_servers():
    registry = ToolRegistry()
    conn1 = FakeConn([FakeMcpTool("search", "search tool")])
    conn2 = FakeConn([FakeMcpTool("fetch", "fetch tool")])
    conn1.config = SimpleNamespace(name="server1", display_name="Server 1")
    conn2.config = SimpleNamespace(name="server2", display_name="Server 2")
    manager = FakeManager({"server1": conn1, "server2": conn2})

    mcp_tools.register_mcp_tools(registry, manager)

    assert registry.get("mcp__server1__search") is not None
    assert registry.get("mcp__server2__fetch") is not None


@pytest.mark.asyncio
async def test_mcp_handler_returns_result():
    registry = ToolRegistry()
    conn = FakeConn([FakeMcpTool("my_tool", "test")])
    manager = FakeManager({"test_server": conn})

    mcp_tools.register_mcp_tools(registry, manager)

    result = await registry.execute("mcp__test_server__my_tool", {"arg": "val"})
    assert "called my_tool" in result


@pytest.mark.asyncio
async def test_mcp_handler_returns_error_for_disconnected():
    registry = ToolRegistry()
    conn = FakeConn([FakeMcpTool("my_tool", "test")])
    manager = FakeManager({"test_server": conn})

    mcp_tools.register_mcp_tools(registry, manager)

    # Disconnect after registration
    conn.is_connected = False

    result = await registry.execute("mcp__test_server__my_tool", {})
    assert "not connected" in result

from __future__ import annotations

from pathlib import Path

import pytest

from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_execute_returns_error_for_unknown_tool():
    registry = ToolRegistry()
    result = await registry.execute("nonexistent", {}, context=None)
    assert "not available" in result


@pytest.mark.asyncio
async def test_execute_calls_sync_handler_in_thread():
    registry = ToolRegistry()

    @registry.register(
        name="sync_tool",
        description="sync",
        parameters={"type": "object", "properties": {}},
    )
    def sync_tool(x: int = 0, context=None):
        return f"sync:{x}"

    result = await registry.execute("sync_tool", {"x": 42}, context=None)
    assert result == "sync:42"


@pytest.mark.asyncio
async def test_execute_passes_context_when_present():
    registry = ToolRegistry()

    @registry.register(
        name="ctx_tool",
        description="ctx",
        parameters={"type": "object", "properties": {}},
    )
    async def ctx_tool(context=None):
        return f"ws={context.workspace}"

    ctx = AgentContext(workspace=Path("/tmp"))
    result = await registry.execute("ctx_tool", {}, context=ctx)
    assert "ws=/tmp" in result


@pytest.mark.asyncio
async def test_execute_reports_missing_required_args():
    registry = ToolRegistry()

    @registry.register(
        name="needs_arg",
        description="needs arg",
        parameters={"type": "object", "properties": {"x": {"type": "string"}}},
    )
    async def needs_arg(x: str, context=None):
        return x

    result = await registry.execute("needs_arg", {}, context=None)
    assert "without any arguments" in result
    assert "x" in result


@pytest.mark.asyncio
async def test_execute_returns_error_string_on_exception():
    registry = ToolRegistry()

    @registry.register(
        name="boom",
        description="boom",
        parameters={"type": "object", "properties": {}},
    )
    async def boom(context=None):
        raise ValueError("crash")

    result = await registry.execute("boom", {}, context=None)
    assert "Error executing boom" in result
    assert "crash" in result


@pytest.mark.asyncio
async def test_deny_permission_blocks_execution():
    registry = ToolRegistry()

    @registry.register(
        name="dangerous",
        description="d",
        parameters={"type": "object", "properties": {}},
        requires_permission=True,
    )
    async def dangerous(context=None):
        return "should not reach"

    ctx = AgentContext(workspace=Path.cwd())
    ctx.tool_permissions["dangerous"] = "deny"

    result = await registry.execute("dangerous", {}, context=ctx)
    assert "disabled" in result


@pytest.mark.asyncio
async def test_confirm_permission_calls_callback():
    registry = ToolRegistry()

    @registry.register(
        name="confirm_me",
        description="c",
        parameters={"type": "object", "properties": {}},
        requires_permission=True,
    )
    async def confirm_me(context=None):
        return "ok"

    approved_flag = {"value": False}

    async def fake_confirm(name, args):
        approved_flag["value"] = True
        return True

    ctx = AgentContext(workspace=Path.cwd(), confirm_callback=fake_confirm)
    result = await registry.execute("confirm_me", {}, context=ctx)

    assert result == "ok"
    assert approved_flag["value"] is True
    assert "confirm_me" in ctx.approved_tools


@pytest.mark.asyncio
async def test_confirm_permission_denied_by_user():
    registry = ToolRegistry()

    @registry.register(
        name="confirm_deny",
        description="c",
        parameters={"type": "object", "properties": {}},
        requires_permission=True,
    )
    async def confirm_deny(context=None):
        return "ok"

    async def fake_confirm(name, args):
        return False

    ctx = AgentContext(workspace=Path.cwd(), confirm_callback=fake_confirm)
    result = await registry.execute("confirm_deny", {}, context=ctx)
    assert "denied by user" in result


def test_tool_defs_includes_registered_tools():
    registry = ToolRegistry()

    @registry.register(
        name="my_tool",
        description="desc",
        parameters={"type": "object", "properties": {"x": {"type": "string"}}},
    )
    async def my_tool(x: str = "", context=None):
        return x

    defs = registry.tool_defs()
    assert len(defs) == 1
    assert defs[0]["function"]["name"] == "my_tool"


def test_tool_info_list_shows_permission_info():
    registry = ToolRegistry()

    @registry.register(
        name="auto_tool",
        description="a",
        parameters={},
    )
    async def auto_tool(context=None):
        return ""

    @registry.register(
        name="perm_tool",
        description="p",
        parameters={},
        requires_permission=True,
    )
    async def perm_tool(context=None):
        return ""

    info = registry.tool_info_list()
    perms = {item["name"]: item["default_permission"] for item in info}
    assert perms["auto_tool"] == "auto"
    assert perms["perm_tool"] == "confirm"

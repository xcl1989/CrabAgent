"""Tests for memory tools (save/recall/replace/list/forget)."""
from __future__ import annotations

from pathlib import Path

import pytest

from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.tools.registry import ToolRegistry
from crabagent.core.agent.tools import memory as memory_tools


def _get_tool(registry: ToolRegistry, name: str):
    tool = registry.get(name)
    assert tool is not None
    return tool.handler


@pytest.mark.asyncio
async def test_memory_save_requires_session():
    registry = ToolRegistry()
    memory_tools.memory_save.__wrapped__ = memory_tools.memory_save
    # Call without context
    result = await memory_tools.memory_save.__wrapped__(
        memory_type="team", category="tech_stack", key="k", content="v",
    )
    assert "requires an active session" in result


@pytest.mark.asyncio
async def test_memory_save_requires_user_id():
    ctx = AgentContext(workspace=Path.cwd())
    # No user_id in metadata
    from crabagent.core.agent.tools.memory import memory_save

    result = await memory_save(
        memory_type="team", category="tech_stack", key="k", content="v", context=ctx,
    )
    assert "no user_id" in result


@pytest.mark.asyncio
async def test_memory_save_truncates_long_content(monkeypatch: pytest.MonkeyPatch):
    ctx = AgentContext(workspace=Path.cwd())
    ctx.metadata["user_id"] = 1
    saved = {}

    async def fake_upsert(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr("crabagent.core.database.agent_memory_upsert", fake_upsert)

    long = "A" * 5000
    await memory_tools.memory_save(
        memory_type="team", category="x", key="k", content=long, context=ctx,
    )

    assert len(saved["content"]) == 3000


@pytest.mark.asyncio
async def test_memory_save_clamps_importance_and_confidence(monkeypatch: pytest.MonkeyPatch):
    ctx = AgentContext(workspace=Path.cwd())
    ctx.metadata["user_id"] = 1
    saved = {}

    async def fake_upsert(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr("crabagent.core.database.agent_memory_upsert", fake_upsert)

    await memory_tools.memory_save(
        memory_type="team", category="x", key="k", content="v",
        importance=5.0, confidence=-1.0, context=ctx,
    )

    assert saved["importance"] == 1.0
    assert saved["confidence"] == 0.0


@pytest.mark.asyncio
async def test_memory_save_success(monkeypatch: pytest.MonkeyPatch):
    ctx = AgentContext(workspace=Path.cwd())
    ctx.metadata["user_id"] = 1
    ctx.metadata["_sub_agent_name"] = "coder"
    ctx.metadata["session_id"] = "s1"
    saved = {}

    async def fake_upsert(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr("crabagent.core.database.agent_memory_upsert", fake_upsert)

    result = await memory_tools.memory_save(
        memory_type="lesson", category="effective_strategy", key="lesson:1",
        content="Test lesson", context=ctx,
    )

    assert "Memory saved" in result
    assert saved["agent_name"] == "coder"
    assert saved["source_session"] == "s1"


@pytest.mark.asyncio
async def test_memory_recall_no_results(monkeypatch: pytest.MonkeyPatch):
    ctx = AgentContext(workspace=Path.cwd())
    ctx.metadata["user_id"] = 1

    async def fake_search(*a, **kw):
        return []

    monkeypatch.setattr("crabagent.core.database.agent_memory_search_vector", fake_search)

    result = await memory_tools.memory_recall("test", context=ctx)
    assert "No memories found" in result


@pytest.mark.asyncio
async def test_memory_recall_formats_results(monkeypatch: pytest.MonkeyPatch):
    ctx = AgentContext(workspace=Path.cwd())
    ctx.metadata["user_id"] = 1

    async def fake_search(*a, **kw):
        return [
            {"key": "k1", "memory_type": "team", "agent_name": "", "importance": 0.9, "content": "val1", "_similarity": 0.85},
            {"key": "k2", "memory_type": "lesson", "agent_name": "coder", "importance": 0.7, "content": "val2"},
        ]

    monkeypatch.setattr("crabagent.core.database.agent_memory_search_vector", fake_search)

    result = await memory_tools.memory_recall("test", context=ctx)
    assert "k1" in result
    assert "0.85" in result
    assert "[coder]" in result


@pytest.mark.asyncio
async def test_memory_recall_requires_session():
    result = await memory_tools.memory_recall("test")
    assert "requires an active session" in result


@pytest.mark.asyncio
async def test_memory_replace_success(monkeypatch: pytest.MonkeyPatch):
    ctx = AgentContext(workspace=Path.cwd())
    ctx.metadata["user_id"] = 1

    async def fake_replace(*a, **kw):
        return True

    monkeypatch.setattr("crabagent.core.database.agent_memory_replace", fake_replace)

    result = await memory_tools.memory_replace("key1", "old", "new", context=ctx)
    assert "Memory updated" in result


@pytest.mark.asyncio
async def test_memory_replace_not_found(monkeypatch: pytest.MonkeyPatch):
    ctx = AgentContext(workspace=Path.cwd())
    ctx.metadata["user_id"] = 1

    async def fake_replace(*a, **kw):
        return False

    monkeypatch.setattr("crabagent.core.database.agent_memory_replace", fake_replace)

    result = await memory_tools.memory_replace("key1", "old", "new", context=ctx)
    assert "not found" in result


@pytest.mark.asyncio
async def test_memory_list_empty(monkeypatch: pytest.MonkeyPatch):
    ctx = AgentContext(workspace=Path.cwd())
    ctx.metadata["user_id"] = 1

    async def fake_list(*a, **kw):
        return []

    monkeypatch.setattr("crabagent.core.database.agent_memory_list_all", fake_list)

    result = await memory_tools.memory_list(context=ctx)
    assert "No memories" in result


@pytest.mark.asyncio
async def test_memory_list_formats_items(monkeypatch: pytest.MonkeyPatch):
    ctx = AgentContext(workspace=Path.cwd())
    ctx.metadata["user_id"] = 1

    async def fake_list(*a, **kw):
        return [
            {"key": "k1", "memory_type": "team", "agent_name": "", "importance": 0.9, "content": "short"},
            {"key": "k2", "memory_type": "lesson", "agent_name": "coder", "importance": 0.5, "content": "A" * 200},
        ]

    monkeypatch.setattr("crabagent.core.database.agent_memory_list_all", fake_list)

    result = await memory_tools.memory_list(context=ctx)
    assert "k1" in result
    assert "..." in result  # truncated preview


@pytest.mark.asyncio
async def test_memory_forget_success(monkeypatch: pytest.MonkeyPatch):
    ctx = AgentContext(workspace=Path.cwd())
    ctx.metadata["user_id"] = 1

    async def fake_delete(*a, **kw):
        return True

    monkeypatch.setattr("crabagent.core.database.agent_memory_delete", fake_delete)

    result = await memory_tools.memory_forget("key1", context=ctx)
    assert "Memory deleted" in result


@pytest.mark.asyncio
async def test_memory_forget_not_found(monkeypatch: pytest.MonkeyPatch):
    ctx = AgentContext(workspace=Path.cwd())
    ctx.metadata["user_id"] = 1

    async def fake_delete(*a, **kw):
        return False

    monkeypatch.setattr("crabagent.core.database.agent_memory_delete", fake_delete)

    result = await memory_tools.memory_forget("key1", context=ctx)
    assert "not found" in result

"""Tests for shared workspace tools (put/get/list)."""
from __future__ import annotations

from pathlib import Path

import pytest

from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.tools import shared as shared_tools


@pytest.mark.asyncio
async def test_shared_put_requires_session():
    result = await shared_tools.shared_put("k", "v")
    assert "requires an active session" in result


@pytest.mark.asyncio
async def test_shared_put_requires_session_id():
    ctx = AgentContext(workspace=Path.cwd())
    result = await shared_tools.shared_put("k", "v", context=ctx)
    assert "no active session" in result


@pytest.mark.asyncio
async def test_shared_put_truncates_long_value(monkeypatch: pytest.MonkeyPatch):
    ctx = AgentContext(workspace=Path.cwd())
    ctx.metadata["session_id"] = "s1"
    saved = {}

    async def fake_put(session_id, key, value, author):
        saved["session_id"] = session_id
        saved["key"] = key
        saved["value"] = value
        saved["author"] = author

    monkeypatch.setattr("crabagent.core.database.shared_memory_put", fake_put)

    long_val = "A" * 20000
    result = await shared_tools.shared_put("key", long_val, context=ctx)

    assert len(saved["value"]) == 10000
    assert "Saved" in result


@pytest.mark.asyncio
async def test_shared_put_success(monkeypatch: pytest.MonkeyPatch):
    ctx = AgentContext(workspace=Path.cwd())
    ctx.metadata["session_id"] = "s1"
    ctx.metadata["_sub_agent_name"] = "researcher"
    saved = {}

    async def fake_put(session_id, key, value, author):
        saved.update(session_id=session_id, key=key, value=value, author=author)

    monkeypatch.setattr("crabagent.core.database.shared_memory_put", fake_put)

    result = await shared_tools.shared_put("findings", "test data", context=ctx)

    assert "Saved" in result
    assert saved["author"] == "researcher"


@pytest.mark.asyncio
async def test_shared_get_returns_value(monkeypatch: pytest.MonkeyPatch):
    ctx = AgentContext(workspace=Path.cwd())
    ctx.metadata["session_id"] = "s1"

    async def fake_get(session_id, key):
        return "the value"

    monkeypatch.setattr("crabagent.core.database.shared_memory_get", fake_get)

    result = await shared_tools.shared_get("findings", context=ctx)
    assert result == "the value"


@pytest.mark.asyncio
async def test_shared_get_not_found(monkeypatch: pytest.MonkeyPatch):
    ctx = AgentContext(workspace=Path.cwd())
    ctx.metadata["session_id"] = "s1"

    async def fake_get(session_id, key):
        return None

    monkeypatch.setattr("crabagent.core.database.shared_memory_get", fake_get)

    result = await shared_tools.shared_get("missing", context=ctx)
    assert "not found" in result


@pytest.mark.asyncio
async def test_shared_list_empty(monkeypatch: pytest.MonkeyPatch):
    ctx = AgentContext(workspace=Path.cwd())
    ctx.metadata["session_id"] = "s1"

    async def fake_get_all(session_id):
        return []

    monkeypatch.setattr("crabagent.core.database.shared_memory_get_all", fake_get_all)

    result = await shared_tools.shared_list(context=ctx)
    assert "empty" in result.lower()


@pytest.mark.asyncio
async def test_shared_list_formats_items(monkeypatch: pytest.MonkeyPatch):
    ctx = AgentContext(workspace=Path.cwd())
    ctx.metadata["session_id"] = "s1"

    async def fake_get_all(session_id):
        return [
            {"key": "k1", "value": "short", "author": "coder"},
            {"key": "k2", "value": "A" * 200, "author": ""},
        ]

    monkeypatch.setattr("crabagent.core.database.shared_memory_get_all", fake_get_all)

    result = await shared_tools.shared_list(context=ctx)
    assert "k1" in result
    assert "(by coder)" in result
    assert "..." in result  # truncated preview

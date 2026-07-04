from __future__ import annotations

from types import SimpleNamespace

import pytest

from crabagent.core.agent.tools.registry import ToolRegistry
from crabagent.core.task import tools as task_tools


def _get_tool(registry: ToolRegistry, name: str):
    tool = registry.get(name)
    assert tool is not None
    return tool.handler


@pytest.mark.asyncio
async def test_task_add_parses_datetime_deadline(monkeypatch: pytest.MonkeyPatch):
    registry = ToolRegistry()
    task_tools.register_task_tools(registry)
    handler = _get_tool(registry, "task_add")
    captured = {}

    async def fake_add(db, **kwargs):
        captured.update(kwargs)
        return {"id": 12, "title": kwargs["title"]}

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("crabagent.core.task.store.add_task", fake_add)
    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: FakeSession())

    result = await handler(title="写报告", deadline="2026-07-02 10:30", assignee="xcl", project="Crab", priority="high")

    assert captured["deadline"].hour == 10
    assert "id=12" in result
    assert "🏷️ high" in result


@pytest.mark.asyncio
async def test_task_list_formats_empty_and_populated_results(monkeypatch: pytest.MonkeyPatch):
    registry = ToolRegistry()
    task_tools.register_task_tools(registry)
    handler = _get_tool(registry, "task_list")

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: FakeSession())
    monkeypatch.setattr("crabagent.core.task.store.list_tasks", _async_return([]))
    empty = await handler(status="pending", project="Crab")
    assert "No pending tasks found for project" in empty

    monkeypatch.setattr(
        "crabagent.core.task.store.list_tasks",
        _async_return([
            {
                "id": 1,
                "status": "pending",
                "priority": "high",
                "title": "修 bug",
                "deadline": "2026-07-02T00:00:00",
                "project": "Crab",
                "assignee": "xcl",
                "description": "A" * 100,
            }
        ]),
    )
    filled = await handler(status="pending")
    assert "修 bug" in filled
    assert "👤 xcl" in filled
    assert "…" in filled


@pytest.mark.asyncio
async def test_task_done_and_delete_report_missing(monkeypatch: pytest.MonkeyPatch):
    registry = ToolRegistry()
    task_tools.register_task_tools(registry)
    done_handler = _get_tool(registry, "task_done")
    delete_handler = _get_tool(registry, "task_delete")

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: FakeSession())
    monkeypatch.setattr("crabagent.core.task.store.update_task", _async_return(None))
    monkeypatch.setattr("crabagent.core.task.store.delete_task", _async_return(False))

    assert await done_handler(id=99) == "❌ Task 99 not found."
    assert await delete_handler(id=99) == "❌ Task 99 not found."


@pytest.mark.asyncio
async def test_task_update_reports_changed_fields(monkeypatch: pytest.MonkeyPatch):
    registry = ToolRegistry()
    task_tools.register_task_tools(registry)
    handler = _get_tool(registry, "task_update")
    captured = {}

    async def fake_update(db, task_id, user_id, **kwargs):
        captured.update(kwargs)
        return {"title": "修 bug"}

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: FakeSession())
    monkeypatch.setattr("crabagent.core.task.store.update_task", fake_update)

    result = await handler(id=1, deadline="2026-07-02T10:30", status="in_progress", priority="low")

    assert captured["deadline"].hour == 10
    assert "deadline, status, priority" in result


@pytest.mark.asyncio
async def test_task_update_reports_not_found(monkeypatch: pytest.MonkeyPatch):
    registry = ToolRegistry()
    task_tools.register_task_tools(registry)
    handler = _get_tool(registry, "task_update")

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: FakeSession())
    monkeypatch.setattr("crabagent.core.task.store.update_task", _async_return(None))

    result = await handler(id=1, title="new")

    assert result == "❌ Task 1 not found."


def _async_return(value):
    async def inner(*args, **kwargs):
        return value

    return inner

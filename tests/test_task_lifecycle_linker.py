"""Tests for TaskLifecycleLinker (conversation ↔ task lifecycle)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from crabagent.core.event import AgentEvent, EventType
from crabagent.core.task import service as task_service
from crabagent.core.task.service import TaskLifecycleLinker


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


class _FakeDB:
    async def execute(self, *_a, **_k):
        return _FakeResult([])

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture
def linker():
    return TaskLifecycleLinker(user_id=1, session_id="sess-1")


@pytest.mark.asyncio
async def test_task_created_event_starts_linked_run(linker, monkeypatch: pytest.MonkeyPatch):
    started: list[dict] = []

    async def fake_start(db, task_id, user_id, **kwargs):
        started.append({"task_id": task_id, "user_id": user_id, **kwargs})
        return ({"id": task_id}, 101)

    async def fake_finish(*_a, **_k):  # pragma: no cover - not reached here
        return None

    monkeypatch.setattr(task_service, "start_agent_run", fake_start)
    monkeypatch.setattr(task_service, "finish_agent_run", fake_finish)
    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: _FakeDB())

    linked: list[int] = []
    unlinked: list[int] = []
    await linker.handle_event(
        AgentEvent(type=EventType.TASK_CREATED, data={"task_id": 9, "title": "生成报告"}),
        link_run=linked.append,
        unlink_run=unlinked.append,
    )

    assert started == [
        {
            "task_id": 9,
            "user_id": 1,
            "agent_name": "main",
            "session_id": "sess-1",
            "task_summary": "生成报告",
        }
    ]
    assert linker.run_ids == [101]
    assert linked == [101]
    assert unlinked == []


@pytest.mark.asyncio
async def test_reopened_task_event_starts_fresh_linked_run(linker, monkeypatch: pytest.MonkeyPatch):
    started: list[dict] = []

    async def fake_start(db, task_id, user_id, **kwargs):
        started.append({"task_id": task_id, "user_id": user_id, **kwargs})
        return ({"id": task_id}, 202)

    monkeypatch.setattr(task_service, "start_agent_run", fake_start)
    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: _FakeDB())

    linked: list[int] = []
    await linker.handle_event(
        AgentEvent(
            type=EventType.TASK_UPDATED,
            data={"task_id": 9, "title": "生成报告", "status": "in_progress"},
        ),
        link_run=linked.append,
    )

    assert started == [
        {
            "task_id": 9,
            "user_id": 1,
            "agent_name": "main",
            "session_id": "sess-1",
            "task_summary": "生成报告",
        }
    ]
    assert linker.run_ids == [202]
    assert linked == [202]


@pytest.mark.asyncio
async def test_task_updated_with_run_id_does_not_duplicate_linked_run(linker, monkeypatch: pytest.MonkeyPatch):
    started: list[int] = []

    async def fake_start(*_a, **_k):
        started.append(1)
        return ({"id": 9}, 203)

    monkeypatch.setattr(task_service, "start_agent_run", fake_start)
    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: _FakeDB())

    await linker.handle_event(
        AgentEvent(
            type=EventType.TASK_UPDATED,
            data={"task_id": 9, "status": "in_progress", "run_id": 88},
        )
    )

    assert started == []
    assert linker.run_ids == []


@pytest.mark.asyncio
async def test_agent_end_finishes_linked_runs(linker, monkeypatch: pytest.MonkeyPatch):
    finished: list[dict] = []

    async def fake_finish(db, run_id, user_id, run_status, result_summary="", error=""):
        finished.append(
            {
                "run_id": run_id,
                "user_id": user_id,
                "run_status": run_status,
                "result_summary": result_summary,
                "error": error,
            }
        )
        return {"id": 1}

    monkeypatch.setattr(task_service, "finish_agent_run", fake_finish)
    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: _FakeDB())

    linker.run_ids = [7, 8]
    linked: list[int] = []
    unlinked: list[int] = []
    await linker.handle_event(
        AgentEvent(type=EventType.AGENT_END, data={}),
        link_run=linked.append,
        unlink_run=unlinked.append,
    )

    assert [f["run_id"] for f in finished] == [7, 8]
    assert all(f["run_status"] == "completed" for f in finished)
    assert linker.run_ids == []
    assert unlinked == [7, 8]
    assert linked == []


@pytest.mark.asyncio
async def test_cancelled_agent_end_cancels_linked_runs(linker, monkeypatch: pytest.MonkeyPatch):
    finished: list[dict] = []

    async def fake_finish(db, run_id, user_id, run_status, result_summary="", error=""):
        finished.append(
            {
                "run_id": run_id,
                "run_status": run_status,
                "result_summary": result_summary,
                "error": error,
            }
        )
        return {"id": 1}

    monkeypatch.setattr(task_service, "finish_agent_run", fake_finish)
    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: _FakeDB())

    linker.run_ids = [9]
    await linker.handle_event(AgentEvent(type=EventType.AGENT_END, data={"cancelled": True}))

    assert finished == [
        {
            "run_id": 9,
            "run_status": "cancelled",
            "result_summary": "",
            "error": "user stopped the session",
        }
    ]
    assert linker.run_ids == []


@pytest.mark.asyncio
async def test_agent_error_finishes_runs_as_failed(linker, monkeypatch: pytest.MonkeyPatch):
    finished: list[dict] = []

    async def fake_finish(db, run_id, user_id, run_status, result_summary="", error=""):
        finished.append({"run_id": run_id, "run_status": run_status, "error": error})
        return {"id": 1}

    monkeypatch.setattr(task_service, "finish_agent_run", fake_finish)
    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: _FakeDB())

    linker.run_ids = [5]
    await linker.handle_event(AgentEvent(type=EventType.AGENT_ERROR, data={"error": "超时"}))

    assert finished == [{"run_id": 5, "run_status": "failed", "error": "超时"}]
    assert linker.run_ids == []


@pytest.mark.asyncio
async def test_unrelated_events_are_ignored(linker):
    await linker.handle_event(AgentEvent(type=EventType.TEXT_DELTA, data={"text": "hi"}))
    await linker.handle_event(AgentEvent(type=EventType.TOOL_RESULT, data={"name": "bash"}))
    assert linker.run_ids == []

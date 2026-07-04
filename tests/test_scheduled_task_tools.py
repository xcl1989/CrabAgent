from __future__ import annotations

from types import SimpleNamespace

import pytest

from crabagent.core.agent.tools import scheduled_task as scheduled_task_tools


class FakeDB:
    def __init__(self, task=None, tasks=None):
        self.task = task
        self.tasks = list(tasks or [])
        self.added = []
        self.committed = 0
        self.rolled_back = 0
        self.closed = 0
        self.refreshed = 0

    async def execute(self, statement):
        if self.tasks:
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: list(self.tasks)))
        return SimpleNamespace(scalar_one_or_none=lambda: self.task)

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = 11
        self.added.append(obj)
        self.task = obj

    async def commit(self):
        self.committed += 1

    async def rollback(self):
        self.rolled_back += 1

    async def refresh(self, task):
        self.refreshed += 1

    async def close(self):
        self.closed += 1


class FakeScheduler:
    def __init__(self):
        self.added = []
        self.removed = []

    async def add_task(self, task):
        self.added.append(task)

    async def remove_task(self, task_id):
        self.removed.append(task_id)


@pytest.mark.asyncio
async def test_scheduled_task_create_rejects_bad_cron(monkeypatch: pytest.MonkeyPatch):
    result = await scheduled_task_tools.scheduled_task_create("demo", "q", "0 9 * *", context=None)

    assert "cron" in result.lower()


@pytest.mark.asyncio
async def test_scheduled_task_create_uses_context_model(monkeypatch: pytest.MonkeyPatch):
    db = FakeDB()
    scheduler = FakeScheduler()

    monkeypatch.setattr(scheduled_task_tools, "_get_db", _async_return(db))
    monkeypatch.setattr("crabagent.serve.scheduler.get_scheduler", lambda: scheduler)

    ctx = SimpleNamespace(model="gpt-4.1", metadata={"resolved_model": "gpt-4.1"}, locale="en")
    result = await scheduled_task_tools.scheduled_task_create("demo", "q", "0 9 * * *", context=ctx)

    assert db.added[0].model == "gpt-4.1"
    assert scheduler.added and scheduler.added[0].name == "demo"
    assert "demo" in result


@pytest.mark.asyncio
async def test_scheduled_task_list_formats_show_all(monkeypatch: pytest.MonkeyPatch):
    tasks = [
        SimpleNamespace(
            id=1,
            enabled=True,
            name="Daily",
            cron_expression="0 9 * * *",
            model="gpt-4o",
            last_run_at=None,
            last_status="",
            prompt="summarize project",
            last_error="",
        )
    ]
    db = FakeDB(tasks=tasks)
    monkeypatch.setattr(scheduled_task_tools, "_get_db", _async_return(db))

    result = await scheduled_task_tools.scheduled_task_list(context=SimpleNamespace(locale="en", metadata={}))

    assert "Daily" in result
    assert "summarize project" in result


@pytest.mark.asyncio
async def test_scheduled_task_update_reports_no_changes(monkeypatch: pytest.MonkeyPatch):
    task = SimpleNamespace(id=1, name="Daily", prompt="q", cron_expression="0 9 * * *")
    db = FakeDB(task=task)
    monkeypatch.setattr(scheduled_task_tools, "_get_db", _async_return(db))

    result = await scheduled_task_tools.scheduled_task_update(1, context=SimpleNamespace(locale="en", metadata={}))

    assert "not modified" in result


@pytest.mark.asyncio
async def test_scheduled_task_update_changes_cron_and_reschedules(monkeypatch: pytest.MonkeyPatch):
    task = SimpleNamespace(id=1, name="Daily", prompt="q", cron_expression="0 9 * * *")
    db = FakeDB(task=task)
    scheduler = FakeScheduler()
    monkeypatch.setattr(scheduled_task_tools, "_get_db", _async_return(db))
    monkeypatch.setattr("crabagent.serve.scheduler.get_scheduler", lambda: scheduler)

    result = await scheduled_task_tools.scheduled_task_update(
        1,
        cron_expression="30 10 * * *",
        context=SimpleNamespace(locale="en", metadata={}),
    )

    assert task.cron_expression == "30 10 * * *"
    assert scheduler.removed == [1]
    assert scheduler.added == [task]
    assert "cron" in result.lower()


@pytest.mark.asyncio
async def test_scheduled_task_delete_removes_from_scheduler(monkeypatch: pytest.MonkeyPatch):
    db = FakeDB()
    scheduler = FakeScheduler()
    monkeypatch.setattr(scheduled_task_tools, "_get_db", _async_return(db))
    monkeypatch.setattr("crabagent.serve.scheduler.get_scheduler", lambda: scheduler)

    result = await scheduled_task_tools.scheduled_task_delete(3, context=SimpleNamespace(locale="en", metadata={}))

    assert scheduler.removed == [3]
    assert db.committed == 1
    assert "3" in result


@pytest.mark.asyncio
async def test_scheduled_task_pause_and_resume_toggle_enabled(monkeypatch: pytest.MonkeyPatch):
    task = SimpleNamespace(id=7, name="Weekly", cron_expression="0 9 * * 1", enabled=True)
    scheduler = FakeScheduler()

    pause_db = FakeDB(task=task)
    monkeypatch.setattr(scheduled_task_tools, "_get_db", _async_return(pause_db))
    monkeypatch.setattr("crabagent.serve.scheduler.get_scheduler", lambda: scheduler)
    paused = await scheduled_task_tools.scheduled_task_pause(7, context=SimpleNamespace(locale="en", metadata={}))

    assert task.enabled is False
    assert scheduler.removed == [7]
    assert "Weekly" in paused

    resume_db = FakeDB(task=task)
    monkeypatch.setattr(scheduled_task_tools, "_get_db", _async_return(resume_db))
    resumed = await scheduled_task_tools.scheduled_task_resume(7, context=SimpleNamespace(locale="en", metadata={}))

    assert task.enabled is True
    assert scheduler.added == [task]
    assert "Weekly" in resumed


def _async_return(value):
    async def inner(*args, **kwargs):
        return value

    return inner

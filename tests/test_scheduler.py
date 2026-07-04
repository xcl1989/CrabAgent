from __future__ import annotations

import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from crabagent.serve.scheduler import SchedulerService


class FakeJob:
    def __init__(self, job_id: str, next_run_time=None):
        self.id = job_id
        self.next_run_time = next_run_time


class FakeScheduler:
    def __init__(self):
        self.jobs = {}
        self.removed = []

    def add_job(self, func, trigger=None, args=None, id=None, replace_existing=True):
        job = FakeJob(id, datetime.datetime(2026, 7, 1, 9, 0))
        self.jobs[id] = job
        return job

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def remove_job(self, job_id):
        self.removed.append(job_id)
        self.jobs.pop(job_id, None)


@pytest.mark.asyncio
async def test_parse_cron_rejects_wrong_field_count():
    service = SchedulerService()

    with pytest.raises(ValueError):
        service._parse_cron("0 9 * *")


def test_remove_task_removes_existing_job():
    service = SchedulerService()
    service._scheduler = FakeScheduler()
    service._job_ids[5] = "st_5"
    service._scheduler.jobs["st_5"] = FakeJob("st_5")

    service.remove_task(5)

    assert service._scheduler.removed == ["st_5"]
    assert 5 not in service._job_ids


def test_remove_task_ignores_missing_job_instance():
    service = SchedulerService()
    service._scheduler = FakeScheduler()
    service._job_ids[5] = "st_5"

    service.remove_task(5)

    assert service._scheduler.removed == []
    assert 5 not in service._job_ids


@pytest.mark.asyncio
async def test_add_task_skips_disabled_task():
    service = SchedulerService()
    service._scheduler = FakeScheduler()
    task = SimpleNamespace(id=3, enabled=False, cron_expression="0 9 * * *", name="demo")

    await service.add_task(task)

    assert service._job_ids == {}
    assert service._scheduler.jobs == {}


@pytest.mark.asyncio
async def test_add_task_skips_invalid_cron(monkeypatch: pytest.MonkeyPatch):
    service = SchedulerService()
    service._scheduler = FakeScheduler()
    task = SimpleNamespace(id=1, enabled=True, cron_expression="bad cron", name="demo")

    def bad_cron(expr: str):
        raise ValueError("bad cron")

    monkeypatch.setattr(service, "_parse_cron", bad_cron)
    await service.add_task(task)

    assert service._job_ids == {}


@pytest.mark.asyncio
async def test_run_agent_uses_default_model_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    service = SchedulerService()
    task = SimpleNamespace(id=9, user_id=1, name="digest", prompt="do work", model="")
    recorded = {}

    class FakeAsyncSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, statement):
            return SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(value="gpt-4.1"))

    class FakeFactory:
        def __call__(self):
            return FakeAsyncSession()

    async def fake_create_conversation(user_id, name, workspace, model, session_id):
        recorded["create_conversation"] = (user_id, name, workspace, model, session_id)
        return 123

    class FakePersistence:
        def __init__(self, conversation_id, branch_id):
            recorded["persistence"] = (conversation_id, branch_id)

        async def on_event(self, event):
            return None

    class FakeRunRecorder:
        def __init__(self, user_id, session_id, model):
            recorded["run_recorder"] = (user_id, session_id, model)

        async def on_event(self, event):
            return None

    async def fake_run_agent(context, prompt):
        recorded["context_model"] = context.model
        recorded["prompt"] = prompt
        return []

    async def fake_commit(task_id, conversation_id, error):
        recorded["commit"] = (task_id, conversation_id, error)

    async def fake_notification(user_id, title, body, conversation_id, category=""):
        recorded.setdefault("notifications", []).append((user_id, title, body, conversation_id, category))

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("crabagent.serve.scheduler.async_session_factory", FakeFactory())
    monkeypatch.setattr("crabagent.core.database.async_session_factory", FakeFactory())
    monkeypatch.setattr("crabagent.serve.scheduler._generate_session_id", lambda: "sess-1")
    monkeypatch.setattr("crabagent.serve.scheduler._create_conversation", fake_create_conversation)
    monkeypatch.setattr("crabagent.serve.services.persistence.PersistenceListener", FakePersistence)
    monkeypatch.setattr("crabagent.core.agent.run_recorder.RunRecorder", FakeRunRecorder)
    monkeypatch.setattr("crabagent.core.agent.loop.run_agent", fake_run_agent)
    monkeypatch.setattr(service, "_commit_task_status", fake_commit)
    monkeypatch.setattr(service, "_create_notification", fake_notification)
    monkeypatch.setattr("crabagent.core.tool_loader.discover_and_register_tools", lambda registry, workspace: None)
    monkeypatch.setattr("crabagent.core.agent.skill.loader.discover_skills", lambda dirs: {})
    monkeypatch.setattr("crabagent.core.agent.skill.loader.register_skill_tool", lambda registry, skills: None)
    monkeypatch.setattr("crabagent.core.molt.tools.register_molt_tools", lambda registry: None)
    monkeypatch.setattr("crabagent.core.todo.tools.register_todo_tools", lambda registry: None)
    monkeypatch.setattr("crabagent.core.task.tools.register_task_tools", lambda registry: None)
    monkeypatch.setattr("crabagent.core.meeting.tools.register_meeting_tools", lambda registry: None)
    monkeypatch.setattr("crabagent.core.mail.tools.register_mail_tools", lambda registry: None)
    monkeypatch.setattr("crabagent.core.calendar.tools.register_calendar_tools", lambda registry: None)
    monkeypatch.setattr("crabagent.core.mcp.client.MCPClientManager", lambda: SimpleNamespace(start_all=_async_noop, stop_all=_async_noop))
    monkeypatch.setattr("crabagent.core.mcp.tools.register_mcp_tools", lambda registry, manager: None)
    monkeypatch.setattr("crabagent.core.config.settings", SimpleNamespace(default_model="gpt-4o", max_iterations=5, auto_approve_tools=False, skill_discovery_dirs=lambda: []))

    session_id = await service._run_agent(task)

    assert session_id == "sess-1"
    assert recorded["context_model"] == "gpt-4.1"
    assert recorded["create_conversation"][3] == "gpt-4.1"
    assert recorded["notifications"][0][4] == "scheduled_task"


@pytest.mark.asyncio
async def test_run_agent_reports_failure_and_resets_auto_approve(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    service = SchedulerService()
    task = SimpleNamespace(id=2, user_id=1, name="fail", prompt="boom", model="custom")
    captured = {}
    settings_obj = SimpleNamespace(default_model="gpt-4o", max_iterations=5, auto_approve_tools=False, skill_discovery_dirs=lambda: [])

    class FakeAsyncSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, statement):
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("crabagent.serve.scheduler.async_session_factory", lambda: FakeAsyncSession())
    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: FakeAsyncSession())
    monkeypatch.setattr("crabagent.serve.scheduler._generate_session_id", lambda: "sess-err")
    monkeypatch.setattr("crabagent.serve.scheduler._create_conversation", _async_return(99))
    monkeypatch.setattr("crabagent.serve.services.persistence.PersistenceListener", lambda conversation_id, branch_id: SimpleNamespace(on_event=_async_noop))
    monkeypatch.setattr("crabagent.core.agent.run_recorder.RunRecorder", lambda user_id, session_id, model: SimpleNamespace(on_event=_async_noop))
    monkeypatch.setattr("crabagent.core.tool_loader.discover_and_register_tools", lambda registry, workspace: None)
    monkeypatch.setattr("crabagent.core.agent.skill.loader.discover_skills", lambda dirs: {})
    monkeypatch.setattr("crabagent.core.agent.skill.loader.register_skill_tool", lambda registry, skills: None)
    monkeypatch.setattr("crabagent.core.molt.tools.register_molt_tools", lambda registry: None)
    monkeypatch.setattr("crabagent.core.todo.tools.register_todo_tools", lambda registry: None)
    monkeypatch.setattr("crabagent.core.task.tools.register_task_tools", lambda registry: None)
    monkeypatch.setattr("crabagent.core.meeting.tools.register_meeting_tools", lambda registry: None)
    monkeypatch.setattr("crabagent.core.mail.tools.register_mail_tools", lambda registry: None)
    monkeypatch.setattr("crabagent.core.calendar.tools.register_calendar_tools", lambda registry: None)
    monkeypatch.setattr("crabagent.core.mcp.client.MCPClientManager", lambda: SimpleNamespace(start_all=_async_noop, stop_all=_async_noop))
    monkeypatch.setattr("crabagent.core.mcp.tools.register_mcp_tools", lambda registry, manager: None)
    monkeypatch.setattr("crabagent.core.config.settings", settings_obj)

    async def failing_run_agent(context, prompt):
        raise RuntimeError("bad agent")

    async def fake_commit(task_id, conversation_id, error):
        captured["commit"] = (task_id, conversation_id, str(error))

    async def fake_notification(user_id, title, body, conversation_id, category=""):
        captured["notification"] = (user_id, title, body, conversation_id, category)

    monkeypatch.setattr("crabagent.core.agent.loop.run_agent", failing_run_agent)
    monkeypatch.setattr(service, "_commit_task_status", fake_commit)
    monkeypatch.setattr(service, "_create_notification", fake_notification)

    session_id = await service._run_agent(task)

    assert session_id == "sess-err"
    assert captured["commit"][2] == "bad agent"
    assert captured["notification"][2].startswith("执行失败")
    assert settings_obj.auto_approve_tools is False


@pytest.mark.asyncio
async def test_run_agent_closes_mcp_manager_after_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    service = SchedulerService()
    task = SimpleNamespace(id=8, user_id=1, name="cleanup", prompt="ok", model="")
    flags = {"mcp_started": False, "mcp_stopped": False}
    settings_obj = SimpleNamespace(default_model="gpt-4o", max_iterations=5, auto_approve_tools=False, skill_discovery_dirs=lambda: [])

    class FakeAsyncSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, statement):
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    class FakeMCPManager:
        async def start_all(self):
            flags["mcp_started"] = True

        async def stop_all(self):
            flags["mcp_stopped"] = True

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("crabagent.serve.scheduler.async_session_factory", lambda: FakeAsyncSession())
    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: FakeAsyncSession())
    monkeypatch.setattr("crabagent.serve.scheduler._generate_session_id", lambda: "sess-clean")
    monkeypatch.setattr("crabagent.serve.scheduler._create_conversation", _async_return(55))
    monkeypatch.setattr("crabagent.serve.services.persistence.PersistenceListener", lambda conversation_id, branch_id: SimpleNamespace(on_event=_async_noop))
    monkeypatch.setattr("crabagent.core.agent.run_recorder.RunRecorder", lambda user_id, session_id, model: SimpleNamespace(on_event=_async_noop))
    monkeypatch.setattr("crabagent.core.agent.loop.run_agent", _async_return([]))
    monkeypatch.setattr(service, "_commit_task_status", _async_noop)
    monkeypatch.setattr(service, "_create_notification", _async_noop)
    monkeypatch.setattr("crabagent.core.tool_loader.discover_and_register_tools", lambda registry, workspace: None)
    monkeypatch.setattr("crabagent.core.agent.skill.loader.discover_skills", lambda dirs: {})
    monkeypatch.setattr("crabagent.core.agent.skill.loader.register_skill_tool", lambda registry, skills: None)
    monkeypatch.setattr("crabagent.core.molt.tools.register_molt_tools", lambda registry: None)
    monkeypatch.setattr("crabagent.core.todo.tools.register_todo_tools", lambda registry: None)
    monkeypatch.setattr("crabagent.core.task.tools.register_task_tools", lambda registry: None)
    monkeypatch.setattr("crabagent.core.meeting.tools.register_meeting_tools", lambda registry: None)
    monkeypatch.setattr("crabagent.core.mail.tools.register_mail_tools", lambda registry: None)
    monkeypatch.setattr("crabagent.core.calendar.tools.register_calendar_tools", lambda registry: None)
    monkeypatch.setattr("crabagent.core.mcp.client.MCPClientManager", FakeMCPManager)
    monkeypatch.setattr("crabagent.core.mcp.tools.register_mcp_tools", lambda registry, manager: None)
    monkeypatch.setattr("crabagent.core.config.settings", settings_obj)

    session_id = await service._run_agent(task)

    assert session_id == "sess-clean"
    assert flags == {"mcp_started": True, "mcp_stopped": True}
    assert settings_obj.auto_approve_tools is False


@pytest.mark.asyncio
async def test_commit_task_status_updates_success_fields(monkeypatch: pytest.MonkeyPatch):
    service = SchedulerService()
    task = SimpleNamespace(last_status="", last_error="old", last_conversation_id="", last_run_at=None)
    committed = {"count": 0}
    now = datetime.datetime(2026, 7, 2, 10, 0)

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, statement):
            return SimpleNamespace(scalar_one_or_none=lambda: task)

        async def commit(self):
            committed["count"] += 1

    monkeypatch.setattr("crabagent.serve.scheduler.async_session_factory", lambda: FakeSession())
    monkeypatch.setattr("crabagent.serve.scheduler.utcnow", lambda: now)

    await service._commit_task_status(1, "conv-1", None)

    assert task.last_status == "success"
    assert task.last_error == ""
    assert task.last_conversation_id == "conv-1"
    assert task.last_run_at == now
    assert committed["count"] == 1


@pytest.mark.asyncio
async def test_commit_task_status_returns_when_task_missing(monkeypatch: pytest.MonkeyPatch):
    service = SchedulerService()
    committed = {"count": 0}

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, statement):
            return SimpleNamespace(scalar_one_or_none=lambda: None)

        async def commit(self):
            committed["count"] += 1

    monkeypatch.setattr("crabagent.serve.scheduler.async_session_factory", lambda: FakeSession())

    await service._commit_task_status(1, "conv-1", RuntimeError("boom"))

    assert committed["count"] == 0


@pytest.mark.asyncio
async def test_refresh_next_run_updates_task(monkeypatch: pytest.MonkeyPatch):
    service = SchedulerService()
    next_run = datetime.datetime(2026, 7, 3, 9, 30, tzinfo=datetime.timezone.utc)
    service._scheduler = FakeScheduler()
    service._scheduler.jobs["st_7"] = FakeJob("st_7", next_run)
    service._job_ids[7] = "st_7"
    task = SimpleNamespace(next_run_at=None)
    committed = {"count": 0}

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, statement):
            return SimpleNamespace(scalar_one_or_none=lambda: task)

        async def commit(self):
            committed["count"] += 1

    monkeypatch.setattr("crabagent.serve.scheduler.async_session_factory", lambda: FakeSession())

    await service._refresh_next_run(7)

    assert task.next_run_at == next_run.replace(tzinfo=None)
    assert committed["count"] == 1


@pytest.mark.asyncio
async def test_refresh_next_run_skips_when_job_missing():
    service = SchedulerService()
    service._scheduler = FakeScheduler()
    service._job_ids[7] = "st_7"

    await service._refresh_next_run(7)


@pytest.mark.asyncio
async def test_create_notification_persists_and_pushes(monkeypatch: pytest.MonkeyPatch):
    service = SchedulerService()
    added = []
    committed = {"count": 0}
    pushed = []

    class FakeNotification:
        def __init__(self, user_id, title, body, conversation_id):
            self.user_id = user_id
            self.title = title
            self.body = body
            self.conversation_id = conversation_id
            self.id = 99

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def add(self, obj):
            added.append(obj)

        async def commit(self):
            committed["count"] += 1

    async def fake_push(category, title, body, conversation_id):
        pushed.append((category, title, body, conversation_id))

    monkeypatch.setattr("crabagent.serve.scheduler.async_session_factory", lambda: FakeSession())
    monkeypatch.setattr("crabagent.core.database.Notification", FakeNotification)
    monkeypatch.setattr(service, "_push_to_wechat", fake_push)

    await service._create_notification(1, "Title", "Body", "conv-1", category="scheduled_task")

    assert added[0].title == "Title"
    assert committed["count"] == 1
    assert pushed == [("scheduled_task", "Title", "Body", "conv-1")]


@pytest.mark.asyncio
async def test_create_notification_skips_push_without_category(monkeypatch: pytest.MonkeyPatch):
    service = SchedulerService()

    class FakeNotification:
        def __init__(self, user_id, title, body, conversation_id):
            self.id = 1

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def add(self, obj):
            return None

        async def commit(self):
            return None

    async def bad_push(*args, **kwargs):
        raise AssertionError("should not push")

    monkeypatch.setattr("crabagent.serve.scheduler.async_session_factory", lambda: FakeSession())
    monkeypatch.setattr("crabagent.core.database.Notification", FakeNotification)
    monkeypatch.setattr(service, "_push_to_wechat", bad_push)

    await service._create_notification(1, "Title", "Body", "conv-1", category="")


async def _async_noop(*args, **kwargs):
    return None


def _async_return(value):
    async def inner(*args, **kwargs):
        return value

    return inner

from __future__ import annotations

from types import SimpleNamespace

import pytest

from crabagent.core.agent.tools.registry import ToolRegistry
from crabagent.core.mail import tools as mail_tools


def _get_tool(registry: ToolRegistry, name: str):
    tool = registry.get(name)
    assert tool is not None
    return tool.handler


def test_fmt_task_list_formats_priority_assignee_and_project():
    text = mail_tools._fmt_task_list(
        [{"title": "修复", "priority": "high", "assignee": "xcl", "deadline": "2026-07-02T00:00:00", "project": "Crab"}],
        "待办",
    )

    assert "🔴" in text
    assert "👤 xcl" in text
    assert "[Crab]" in text


@pytest.mark.asyncio
async def test_email_send_success_includes_attachment_count(monkeypatch: pytest.MonkeyPatch):
    registry = ToolRegistry()
    mail_tools.register_mail_tools(registry)
    handler = _get_tool(registry, "email_send")

    monkeypatch.setattr("crabagent.core.mail.handler.send_email", _async_return({"status": "ok", "attachments": 2}))
    result = await handler("a@example.com", "Hi", "Body", attachments=["a", "b"])

    assert "2 attachments" in result


@pytest.mark.asyncio
async def test_email_check_timeout_returns_friendly_message(monkeypatch: pytest.MonkeyPatch):
    import asyncio

    registry = ToolRegistry()
    mail_tools.register_mail_tools(registry)
    handler = _get_tool(registry, "email_check")

    async def fake_wait_for(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr("asyncio.wait_for", fake_wait_for)

    result = await handler(limit=2)

    assert "timed out" in result


@pytest.mark.asyncio
async def test_daily_digest_without_recipient_returns_preview(monkeypatch: pytest.MonkeyPatch):
    registry = ToolRegistry()
    mail_tools.register_mail_tools(registry)
    handler = _get_tool(registry, "daily_digest")

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: FakeSession())
    monkeypatch.setattr("crabagent.core.mail.handler.get_config", _async_return(None))
    monkeypatch.setattr("crabagent.core.task.store.get_task_summary", _async_return({"total": 3, "pending": 2, "overdue": 1, "done_today": 0}))
    monkeypatch.setattr("crabagent.core.task.store.list_tasks", _async_side_effect([[], [], [], []]))
    monkeypatch.setattr("crabagent.core.task.store.list_tasks_due_soon", _async_return([]))

    result = await handler()

    assert "Daily Digest Preview" in result
    assert "No email configured" in result


@pytest.mark.asyncio
async def test_task_remind_sends_email_when_tasks_exist(monkeypatch: pytest.MonkeyPatch):
    registry = ToolRegistry()
    mail_tools.register_mail_tools(registry)
    handler = _get_tool(registry, "task_remind")
    sent = {}

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: FakeSession())
    monkeypatch.setattr("crabagent.core.mail.handler.get_config", _async_return(SimpleNamespace(imap_user="me@example.com")))
    monkeypatch.setattr("crabagent.core.task.store.list_tasks_due_soon", _async_return([{"title": "修复", "priority": "medium"}]))
    monkeypatch.setattr("crabagent.core.task.store.list_tasks", _async_return([]))

    async def fake_send_email(**kwargs):
        sent.update(kwargs)
        return {"status": "ok"}

    monkeypatch.setattr("crabagent.core.mail.handler.send_email", fake_send_email)

    result = await handler()

    assert sent["to"] == "me@example.com"
    assert "Reminder sent" in result


@pytest.mark.asyncio
async def test_task_remind_without_tasks_returns_noop(monkeypatch: pytest.MonkeyPatch):
    registry = ToolRegistry()
    mail_tools.register_mail_tools(registry)
    handler = _get_tool(registry, "task_remind")

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: FakeSession())
    monkeypatch.setattr("crabagent.core.mail.handler.get_config", _async_return(None))
    monkeypatch.setattr("crabagent.core.task.store.list_tasks_due_soon", _async_return([]))
    monkeypatch.setattr("crabagent.core.task.store.list_tasks", _async_return([]))

    result = await handler()

    assert result == "✅ No tasks need reminders."


def _async_return(value):
    async def inner(*args, **kwargs):
        return value

    return inner


def _async_side_effect(values):
    iterator = iter(values)

    async def inner(*args, **kwargs):
        return next(iterator)

    return inner

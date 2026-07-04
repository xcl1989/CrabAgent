from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from crabagent.core.event import AgentEvent, EventBus, EventType
from crabagent.serve.services import persistence


class FakeListener:
    def __init__(self):
        self.saved = []

    async def save(self, db, **kwargs):
        self.saved.append(kwargs)
        return SimpleNamespace(id=len(self.saved))


@pytest.mark.asyncio
async def test_on_event_buffers_message_and_flushes(monkeypatch: pytest.MonkeyPatch):
    listener = persistence.PersistenceListener(conversation_id=10, branch_id="main")
    saved_msgs = []

    async def fake_save(db, **kwargs):
        saved_msgs.append(kwargs)
        return SimpleNamespace(id=len(saved_msgs))

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def fake_index(mid, content):
        return None

    monkeypatch.setattr(persistence, "async_session_factory", lambda: FakeSession())
    monkeypatch.setattr(persistence, "save_message", fake_save)
    monkeypatch.setattr("crabagent.core.fts.index_message", fake_index)

    await listener.on_event(
        AgentEvent(
            type=EventType.MESSAGE_CREATED,
            data={
                "message": {
                    "role": "assistant",
                    "content": "hello world",
                    "agent": "default",
                }
            },
        )
    )

    await listener.finalize()

    assert len(saved_msgs) == 1
    assert saved_msgs[0]["conversation_id"] == 10
    assert saved_msgs[0]["role"] == "assistant"
    assert saved_msgs[0]["content"] == "hello world"


@pytest.mark.asyncio
async def test_on_event_serializes_multimodal_content(monkeypatch: pytest.MonkeyPatch):
    listener = persistence.PersistenceListener(conversation_id=2, branch_id="dev")
    saved = []

    async def fake_save(db, **kwargs):
        saved.append(kwargs)
        return SimpleNamespace(id=1)

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(persistence, "async_session_factory", lambda: FakeSession())
    monkeypatch.setattr(persistence, "save_message", fake_save)
    monkeypatch.setattr("crabagent.core.fts.index_message", _async_noop)

    await listener.on_event(
        AgentEvent(
            type=EventType.MESSAGE_CREATED,
            data={
                "message": {
                    "role": "tool",
                    "content": [{"type": "text", "text": "img"}],
                    "tool_call_id": "c1",
                    "name": "screenshot",
                    "agent": "default",
                }
            },
        )
    )
    await listener.finalize()

    parsed = json.loads(saved[0]["content"])
    assert parsed[0]["text"] == "img"
    assert saved[0]["tool_call_id"] == "c1"


@pytest.mark.asyncio
async def test_on_event_ignores_non_message_events():
    listener = persistence.PersistenceListener(conversation_id=3)
    await listener.on_event(AgentEvent(type=EventType.TOOL_CALL, data={}))

    assert listener._buffer == []
    assert listener.sequence == 0


@pytest.mark.asyncio
async def test_on_event_ignores_missing_message_key():
    listener = persistence.PersistenceListener(conversation_id=4)
    await listener.on_event(AgentEvent(type=EventType.MESSAGE_CREATED, data={}))
    assert listener._buffer == []


@pytest.mark.asyncio
async def test_persist_compression_inserts_summary(monkeypatch: pytest.MonkeyPatch):
    listener = persistence.PersistenceListener(conversation_id=5, branch_id="main")

    class FakeExecuteResult:
        pass

    class FakeSession:
        def __init__(self):
            self.executed = []
            self.added = []
            self.committed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, statement):
            self.executed.append(statement)
            return FakeExecuteResult()

        def add(self, obj):
            self.added.append(obj)

        async def commit(self):
            self.committed = True

    session = FakeSession()
    monkeypatch.setattr(persistence, "async_session_factory", lambda: session)

    await listener.persist_compression("summary text")

    assert any("UPDATE" in str(s).upper() for s in session.executed)
    assert session.committed is True
    assert session.added[0].content == "summary text"
    assert session.added[0].role == "compress"


async def _async_noop(*args, **kwargs):
    return None

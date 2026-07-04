from __future__ import annotations

import pytest

from crabagent.core.event import AgentEvent, EventBus, EventType


@pytest.mark.asyncio
async def test_emit_calls_async_and_sync_listeners():
    bus = EventBus(name="test")
    calls = []

    async def async_listener(event):
        calls.append(("async", event.type))

    def sync_listener(event):
        calls.append(("sync", event.type))

    bus.subscribe(async_listener)
    bus.subscribe(sync_listener)

    await bus.emit(AgentEvent(type=EventType.AGENT_START))

    assert ("async", EventType.AGENT_START) in calls
    assert ("sync", EventType.AGENT_START) in calls


@pytest.mark.asyncio
async def test_emit_swallows_listener_exceptions():
    bus = EventBus(name="test")
    called = []

    async def bad_listener(event):
        raise RuntimeError("boom")

    async def good_listener(event):
        called.append(event.type)

    bus.subscribe(bad_listener)
    bus.subscribe(good_listener)

    await bus.emit(AgentEvent(type=EventType.TOOL_CALL))

    assert called == [EventType.TOOL_CALL]


def test_emit_sync_calls_listeners():
    bus = EventBus(name="test")
    events = []
    bus.subscribe(lambda event: events.append(event.type))

    bus.emit_sync(AgentEvent(type=EventType.AGENT_END))

    assert events == [EventType.AGENT_END]


def test_emit_sync_swallows_errors():
    bus = EventBus(name="test")
    bus.subscribe(lambda event: (_ for _ in ()).throw(ValueError("x")))

    # Should not raise
    bus.emit_sync(AgentEvent(type=EventType.AGENT_INFO))


def test_unsubscribe_removes_callback():
    bus = EventBus(name="test")
    called = []

    def listener(event):
        called.append(event.type)

    bus.subscribe(listener)
    bus.unsubscribe(listener)

    bus.emit_sync(AgentEvent(type=EventType.AGENT_START))
    assert called == []


def test_unsubscribe_silently_ignores_missing_callback():
    bus = EventBus(name="test")
    bus.unsubscribe(lambda event: None)  # should not raise


def test_agent_event_to_sse_contains_json():
    event = AgentEvent(type=EventType.TEXT_DELTA, data={"text": "hello"})
    sse = event.to_sse()

    assert sse.startswith("data: ")
    assert sse.endswith("\n\n")
    assert '"text_delta"' in sse
    assert "hello" in sse


def test_agent_event_to_dict_has_timestamp():
    event = AgentEvent(type=EventType.AGENT_START, data={})
    d = event.to_dict()

    assert d["type"] == "agent_start"
    assert "timestamp" in d
    assert d["data"] == {}

"""Tests for RunRecorder event handling."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from crabagent.core.agent.run_recorder import RunRecorder
from crabagent.core.event import AgentEvent, EventType


@pytest.fixture
def recorder():
    return RunRecorder(user_id=1, session_id="s1", model="gpt-4o")


@pytest.mark.asyncio
async def test_on_event_handles_agent_start(recorder, monkeypatch: pytest.MonkeyPatch):
    called = {}

    async def fake_create(**kwargs):
        called.update(kwargs)
        return 42

    monkeypatch.setattr("crabagent.core.database.run_record_create", fake_create)

    await recorder.on_event(
        AgentEvent(type=EventType.AGENT_START, data={"model": "gpt-4o", "query": "hello"})
    )

    assert recorder._main_run_id == 42
    assert called["agent_name"] == "main"


@pytest.mark.asyncio
async def test_on_event_handles_tool_call(recorder, monkeypatch: pytest.MonkeyPatch):
    recorder._main_run_id = 1

    async def fake_create(**kwargs):
        return 99

    monkeypatch.setattr("crabagent.core.database.run_record_create", fake_create)

    await recorder.on_event(
        AgentEvent(type=EventType.TOOL_CALL, data={"name": "bash", "arguments": {"command": "ls"}})
    )

    assert len(recorder._main_tool_buf) == 1


@pytest.mark.asyncio
async def test_on_event_handles_tool_result(recorder, monkeypatch: pytest.MonkeyPatch):
    recorder._main_run_id = 1
    recorder._main_tool_buf = [{"name": "bash", "args": {}, "started_at": 0, "result_summary": None, "elapsed": 0}]

    await recorder.on_event(
        AgentEvent(type=EventType.TOOL_RESULT, data={"name": "bash", "result": "output", "id": "tc1"})
    )

    assert recorder._main_tool_buf[0]["result_summary"] == "output"


@pytest.mark.asyncio
async def test_on_event_swallows_exceptions(recorder, monkeypatch: pytest.MonkeyPatch):
    async def fake_create(**kwargs):
        raise RuntimeError("DB error")

    monkeypatch.setattr("crabagent.core.database.run_record_create", fake_create)

    # Should not raise
    await recorder.on_event(
        AgentEvent(type=EventType.AGENT_START, data={"query": "test"})
    )


@pytest.mark.asyncio
async def test_on_event_ignores_unknown_event_type(recorder):
    await recorder.on_event(AgentEvent(type=EventType.TEXT_DELTA, data={"text": "hi"}))


@pytest.mark.asyncio
async def test_on_event_finalizes_agent_end(recorder, monkeypatch: pytest.MonkeyPatch):
    captured = {}
    recorder._main_run_id = 7
    recorder._main_started_at = 100.0
    recorder._main_tool_buf = [{"name": "bash", "result_summary": "done"}]

    monkeypatch.setattr("crabagent.core.agent.run_recorder._time", SimpleNamespace(time=lambda: 103.24))

    async def fake_finalize(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("crabagent.core.database.run_record_finalize", fake_finalize)

    await recorder.on_event(
        AgentEvent(
            type=EventType.AGENT_END,
            data={"tokens": 10, "iterations": 2, "result": "finished"},
        )
    )

    assert captured == {
        "run_id": 7,
        "status": "completed",
        "elapsed": 3.2,
        "tokens_used": 10,
        "iterations": 2,
        "tool_calls": [{"name": "bash", "result_summary": "done"}],
        "result_summary": "finished",
    }
    assert recorder._main_run_id is None
    assert recorder._main_tool_buf == []


@pytest.mark.asyncio
async def test_on_event_marks_budget_exhausted(recorder, monkeypatch: pytest.MonkeyPatch):
    recorder._main_run_id = 12
    captured = {}

    async def fake_update(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("crabagent.core.database.run_record_update", fake_update)

    await recorder.on_event(
        AgentEvent(type=EventType.BUDGET_EXHAUSTED, data={"reason": "too many tokens"})
    )

    assert captured == {
        "run_id": 12,
        "result_summary": "Budget exhausted: too many tokens",
    }


@pytest.mark.asyncio
async def test_on_event_records_sub_agent_lifecycle(recorder, monkeypatch: pytest.MonkeyPatch):
    created = {}
    finalized = {}
    recorder._pipeline_run_id = 500

    monkeypatch.setattr("crabagent.core.agent.run_recorder._time", SimpleNamespace(time=lambda: 205.55))

    async def fake_create(**kwargs):
        created.update(kwargs)
        return 88

    async def fake_finalize(**kwargs):
        finalized.update(kwargs)

    monkeypatch.setattr("crabagent.core.database.run_record_create", fake_create)
    monkeypatch.setattr("crabagent.core.database.run_record_finalize", fake_finalize)

    await recorder.on_event(
        AgentEvent(
            type=EventType.SUB_AGENT_START,
            data={
                "sub_agent_id": "sub-1",
                "agent_name": "coder",
                "model": "gpt-4.1",
                "task": "write tests",
                "pipeline_step_id": "step-a",
            },
        )
    )
    await recorder.on_event(
        AgentEvent(type=EventType.SUB_AGENT_TOOL_CALL, data={"sub_agent_id": "sub-1", "name": "read", "args": {"file": "x"}})
    )
    await recorder.on_event(
        AgentEvent(type=EventType.SUB_AGENT_TOOL_RESULT, data={"sub_agent_id": "sub-1", "name": "read", "result": "ok"})
    )
    await recorder.on_event(
        AgentEvent(type=EventType.SUB_AGENT_END, data={"sub_agent_id": "sub-1", "tokens": 8, "iterations": 1, "result": "done"})
    )

    assert created["agent_name"] == "coder"
    assert created["parent_run_id"] == 500
    assert created["metadata"] == {"pipeline_step_id": "step-a"}
    assert finalized["run_id"] == 88
    assert finalized["status"] == "completed"
    assert finalized["tokens_used"] == 8
    assert finalized["iterations"] == 1
    assert finalized["result_summary"] == "done"
    assert finalized["tool_calls"][0]["name"] == "read"
    assert finalized["tool_calls"][0]["result_summary"] == "ok"
    assert "sub-1" not in recorder._sub_runs


@pytest.mark.asyncio
async def test_on_event_creates_pipeline_run_and_marks_end(recorder, monkeypatch: pytest.MonkeyPatch):
    created = {}
    updated = {}

    async def fake_create(**kwargs):
        created.update(kwargs)
        return 321

    async def fake_update(**kwargs):
        updated.update(kwargs)

    monkeypatch.setattr("crabagent.core.database.run_record_create", fake_create)
    monkeypatch.setattr("crabagent.core.database.run_record_update", fake_update)

    await recorder.on_event(
        AgentEvent(
            type=EventType.PIPELINE_START,
            data={
                "step_ids": ["a", "b"],
                "step_agents": {"a": "coder", "b": "writer"},
                "step_tasks": {"a": "collect data"},
                "total_steps": 2,
            },
        )
    )
    await recorder.on_event(
        AgentEvent(type=EventType.PIPELINE_STEP_START, data={"step_id": "a", "started_at": 10.0})
    )
    await recorder.on_event(
        AgentEvent(type=EventType.PIPELINE_STEP_END, data={"step_id": "a", "elapsed": 1.5})
    )
    await recorder.on_event(
        AgentEvent(type=EventType.PIPELINE_END, data={"total": 2, "completed": ["a"], "failed": ["b"]})
    )

    assert created["agent_name"] == "pipeline"
    assert created["task_summary"] == "collect data"
    assert created["metadata"] == {
        "pipeline": True,
        "total_steps": 2,
        "step_ids": ["a", "b"],
        "step_agents": {"a": "coder", "b": "writer"},
    }
    assert updated == {
        "run_id": 321,
        "status": "failed",
        "result_summary": "1/2 steps succeeded",
    }
    assert recorder.pipeline_run_id is None
    assert recorder._pipeline_steps == {}


@pytest.mark.asyncio
async def test_pipeline_run_id_property(recorder):
    assert recorder.pipeline_run_id is None

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.tools.registry import ToolRegistry
from crabagent.core.goals import scheduler, service, tools


@pytest.mark.asyncio
async def test_create_goal_rejects_second_open_goal(monkeypatch: pytest.MonkeyPatch):
    existing = SimpleNamespace()

    async def fake_current(*_args, **_kwargs):
        return existing

    monkeypatch.setattr(service, "get_current_goal", fake_current)
    with pytest.raises(ValueError, match="already has an open goal"):
        await service.create_goal(
            SimpleNamespace(),
            session_id="session",
            user_id=1,
            objective="Finish the implementation",
        )


@pytest.mark.asyncio
async def test_update_goal_requires_completion_evidence():
    goal = _goal()
    with pytest.raises(ValueError, match="Completion requires"):
        await service.update_goal(SimpleNamespace(), goal, status="complete")


@pytest.mark.asyncio
async def test_update_goal_completes_with_evidence_and_records_event(monkeypatch: pytest.MonkeyPatch):
    events = []

    async def fake_event(_db, _goal, event_type, detail, data=None):
        events.append((event_type, detail, data))

    goal = _goal()
    monkeypatch.setattr(service, "record_event", fake_event)

    updated = await service.update_goal(SimpleNamespace(), goal, status="complete", evidence="pytest: 20 passed")

    assert updated is goal
    assert goal.status == "complete"
    assert goal.completion_evidence == "pytest: 20 passed"
    assert goal.closed_at is not None
    assert events == [("updated", "Goal status: complete", None)]


@pytest.mark.asyncio
async def test_update_goal_requires_blocker_for_unmet_status():
    with pytest.raises(ValueError, match="concrete blocker"):
        await service.update_goal(SimpleNamespace(), _goal(), status="unmet")


@pytest.mark.asyncio
async def test_checkpoint_updates_goal_and_records_checkpoint_event(monkeypatch: pytest.MonkeyPatch):
    events = []

    async def fake_event(_db, _goal, event_type, detail, data=None):
        events.append((event_type, detail, data))

    class FakeDb:
        def add(self, value):
            self.value = value

    goal = _goal(id=12, latest_checkpoint="", next_step="")
    db = FakeDb()
    monkeypatch.setattr(service, "record_event", fake_event)

    checkpoint = await service.checkpoint_goal(db, goal, "API verified", "Add tool tests")

    assert checkpoint.goal_id == 12
    assert checkpoint.summary == "API verified"
    assert checkpoint.next_step == "Add tool tests"
    assert goal.latest_checkpoint == "API verified"
    assert goal.next_step == "Add tool tests"
    assert events == [("checkpoint", "API verified", {"next_step": "Add tool tests"})]


def test_goal_prompt_keeps_criteria_constraints_and_checkpoint():
    goal = SimpleNamespace(
        objective="Ship goal mode",
        success_criteria=["Tests pass"],
        constraints=["Keep chat output"],
        latest_checkpoint="API is ready",
    )
    prompt = service.goal_prompt(goal)
    assert "Ship goal mode" in prompt
    assert "Tests pass" in prompt
    assert "Keep chat output" in prompt
    assert "API is ready" in prompt


@pytest.mark.asyncio
async def test_auto_continue_goal_gets_safe_default_budgets(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    async def fake_current(*_args, **_kwargs):
        return None

    async def fake_event(*_args, **_kwargs):
        return None

    class FakeDb:
        def add(self, value):
            captured["goal"] = value

        async def flush(self):
            captured["goal"].id = 1

    monkeypatch.setattr(service, "get_current_goal", fake_current)
    monkeypatch.setattr(service, "record_event", fake_event)
    await service.create_goal(
        FakeDb(),
        session_id="session",
        user_id=1,
        objective="Keep working",
        auto_continue=True,
    )
    assert captured["goal"].max_auto_turns == 10
    assert captured["goal"].token_budget == 80_000


@pytest.mark.asyncio
async def test_account_goal_usage_limits_at_token_budget(monkeypatch: pytest.MonkeyPatch):
    events = []

    async def fake_event(_db, _goal, event_type, detail, data=None):
        events.append((event_type, detail))

    goal = SimpleNamespace(
        tokens_used=90, auto_turns=1, token_budget=100, max_auto_turns=None, status="active", stop_reason=""
    )
    monkeypatch.setattr(service, "record_event", fake_event)
    limited = await service.account_goal_usage(SimpleNamespace(), goal, 10)
    assert limited is True
    assert goal.status == "budget_limited"
    assert events[0][0] == "limited"


@pytest.mark.asyncio
async def test_account_goal_usage_records_normal_turn_and_ignores_negative_tokens(monkeypatch: pytest.MonkeyPatch):
    events = []

    async def fake_event(_db, _goal, event_type, detail, data=None):
        events.append((event_type, detail, data))

    goal = SimpleNamespace(
        tokens_used=5, auto_turns=0, token_budget=100, max_auto_turns=5, status="active", stop_reason=""
    )
    monkeypatch.setattr(service, "record_event", fake_event)

    limited = await service.account_goal_usage(SimpleNamespace(), goal, -10)

    assert limited is False
    assert goal.tokens_used == 5
    assert goal.auto_turns == 1
    assert events == [("usage", "Automatic turn 1 completed", None)]


@pytest.mark.parametrize(
    ("snapshot", "metadata", "expected"),
    [
        ({"status": "active", "auto_continue": True}, {}, True),
        ({"status": "active", "auto_continue": True}, {"_agent_error": True}, False),
        ({"status": "active", "auto_continue": True}, {"_run_error": True}, False),
        ({"status": "complete", "auto_continue": True}, {}, False),
    ],
)
def test_goal_continuation_stops_after_failed_turn(snapshot, metadata, expected):
    from crabagent.serve.api.prompt import _should_continue_goal

    assert _should_continue_goal(snapshot, metadata) is expected


def test_goal_continuation_preserves_selected_model_and_provider():
    from crabagent.serve.api.prompt import PromptRequest, _goal_continuation_request

    request = PromptRequest(
        message="Initial goal request",
        model="configured-model",
        provider="configured-provider",
        agent="coder",
        reasoning_effort="high",
        file_context="src/example.py",
        workspace_type="code",
        work_mode=True,
    )

    follow_up = _goal_continuation_request(request)

    assert follow_up.model == "configured-model"
    assert follow_up.provider == "configured-provider"
    assert follow_up.agent == "coder"
    assert follow_up.reasoning_effort == "high"
    assert follow_up.file_context == "src/example.py"
    assert follow_up.workspace_type == "code"
    assert follow_up.work_mode is True


@pytest.mark.asyncio
async def test_goal_tools_register_and_checkpoint_emit_event(monkeypatch: pytest.MonkeyPatch):
    context = AgentContext(workspace=Path.cwd(), tool_registry=ToolRegistry())
    goal = _goal(id=5, latest_checkpoint="", next_step="")
    emitted = []
    captured = {}

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            captured["committed"] = True

    async def fake_current(_db, session_id):
        assert session_id == "session"
        return goal

    async def fake_checkpoint(_db, active_goal, summary, next_step):
        assert active_goal is goal
        goal.latest_checkpoint = summary
        goal.next_step = next_step
        return SimpleNamespace(summary=summary, next_step=next_step)

    async def fake_emit(event):
        emitted.append(event)

    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: FakeSession())
    monkeypatch.setattr(tools, "get_current_goal", fake_current)
    monkeypatch.setattr(tools, "checkpoint_goal", fake_checkpoint)
    context.event_bus.emit = fake_emit
    tools.register_goal_tools(context, "session", 9)

    handler = context.tool_registry.get("checkpoint_goal").handler
    result = await handler(summary="Tests added", next_step="Run suite", context=context)

    assert captured["committed"] is True
    assert result["checkpoint"] == {"summary": "Tests added", "next_step": "Run suite"}
    assert emitted[0].type == "goal_checkpoint"
    assert emitted[0].data["goal"]["latest_checkpoint"] == "Tests added"


@pytest.mark.asyncio
async def test_schedule_goal_continuation_deduplicates_and_cleans_up():
    scheduler._tasks.clear()
    called = []

    async def continuation():
        called.append("run")

    assert scheduler.schedule_goal_continuation("session", continuation, delay_seconds=0) is True
    assert scheduler.schedule_goal_continuation("session", continuation, delay_seconds=0) is False

    for _ in range(3):
        await __import__("asyncio").sleep(0)

    assert called == ["run"]
    assert scheduler._tasks == {}


def _goal(**overrides):
    values = {
        "id": 1,
        "session_id": "session",
        "execution_model": "",
        "execution_provider": "",
        "execution_agent": "",
        "reasoning_effort": "",
        "token_budget": None,
        "tokens_used": 0,
        "max_auto_turns": None,
        "auto_turns": 0,
        "created_at": None,
        "status": "active",
        "completion_evidence": "",
        "objective": "Goal",
        "success_criteria": [],
        "constraints": [],
        "auto_continue": False,
        "blocker": "",
        "stop_reason": "",
        "latest_checkpoint": "",
        "next_step": "",
        "updated_at": None,
        "closed_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)

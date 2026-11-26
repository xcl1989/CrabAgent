"""Permission bubbling: sub-agent confirm/ask requests surface in the parent UI.

Covers:

* ``AgentContext.confirm`` / ``AgentContext.ask`` adapt to the callback's arity
  (serve callbacks take ``origin``; CLI callbacks predate it) by static
  inspection — a ``TypeError`` raised *inside* a callback must NOT trigger a
  second prompt.
* ``spawn_sub_agent`` hands the parent's interactive channel to synchronous
  sub-agents and labels prompts with ``metadata["_agent_origin"]``; background
  sub-agents get neither.
* ``ask_question`` is no longer withheld from sub-agents.
* ``update_goal`` only exposes ``complete`` / ``unmet`` to the agent and refuses
  an early ``unmet`` on auto-continuing goals.
* The automatic goal continuation message asks for an evidence audit.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

import crabagent.core.agent.agents as agents_module
from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.tools.registry import ToolRegistry
from crabagent.core.goals import tools as goal_tools

# ── AgentContext.confirm / .ask ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_without_channel_allows():
    ctx = AgentContext(workspace=Path.cwd())
    assert await ctx.confirm("write", {}) is True


@pytest.mark.asyncio
async def test_confirm_passes_origin_to_three_arg_callback():
    seen = {}

    async def cb(tool_name, args, origin=None):
        seen.update(tool=tool_name, args=args, origin=origin)
        return True

    ctx = AgentContext(workspace=Path.cwd(), confirm_callback=cb)
    ctx.metadata["_agent_origin"] = {"agent_name": "coder", "display_name": "代码专家", "sub_agent_id": "coder_1"}
    assert await ctx.confirm("write", {"file_path": "/x"}) is True
    assert seen["origin"]["agent_name"] == "coder"
    assert seen["args"] == {"file_path": "/x"}


@pytest.mark.asyncio
async def test_confirm_two_arg_cli_callback_receives_no_origin():
    seen = {}

    async def cb(tool_name, args):
        seen["args"] = (tool_name, args)
        return True

    ctx = AgentContext(workspace=Path.cwd(), confirm_callback=cb)
    ctx.metadata["_agent_origin"] = {"agent_name": "coder", "display_name": "代码专家", "sub_agent_id": "coder_1"}
    assert await ctx.confirm("write", {"file_path": "/x"}) is True
    assert len(seen["args"]) == 2


@pytest.mark.asyncio
async def test_confirm_internal_type_error_propagates_without_retry():
    """A TypeError from inside the callback is a real bug, not an arity mismatch."""
    calls = []

    async def cb(tool_name, args, origin=None):
        calls.append(1)
        raise TypeError("json.dumps got a set")

    ctx = AgentContext(workspace=Path.cwd(), confirm_callback=cb)
    ctx.metadata["_agent_origin"] = {"agent_name": "coder", "display_name": "x", "sub_agent_id": "s"}
    with pytest.raises(TypeError):
        await ctx.confirm("write", {})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_ask_without_channel_returns_error():
    ctx = AgentContext(workspace=Path.cwd())
    assert "no ask callback" in await ctx.ask("q")


@pytest.mark.asyncio
async def test_ask_six_arg_callback_receives_recommended_header_origin():
    seen = {}

    async def cb(question, options, multiple, recommended, header, origin):
        seen.update(question=question, recommended=recommended, header=header, origin=origin)
        return "A"

    ctx = AgentContext(workspace=Path.cwd(), ask_callback=cb)
    ctx.metadata["_agent_origin"] = {"agent_name": "coder", "display_name": "x", "sub_agent_id": "s"}
    answer = await ctx.ask("q", ["A", "B"], False, recommended="A", header="策略")
    assert answer == "A"
    assert seen == {
        "question": "q",
        "recommended": "A",
        "header": "策略",
        "origin": {"agent_name": "coder", "display_name": "x", "sub_agent_id": "s"},
    }


@pytest.mark.asyncio
async def test_ask_three_arg_cli_callback_drops_extras():
    seen = {}

    async def cb(question, options, multiple):
        seen["n"] = len([a for a in (question, options, multiple)])
        return "cli"

    ctx = AgentContext(workspace=Path.cwd(), ask_callback=cb)
    assert await ctx.ask("q", ["A"], False, recommended="A", header="h") == "cli"
    assert seen["n"] == 3


def test_max_positional_handles_var_positional():
    async def cb(*args):
        return True

    assert AgentContext._max_positional(cb) >= 99
    assert AgentContext._max_positional(lambda a, b: a) == 2
    # functools.partial and builtins may lack a signature; fall back permissively.
    assert AgentContext._max_positional(print) >= 0


# ── spawn_sub_agent channel inheritance ──────────────────────────────────────


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


def _fake_registry(names):
    reg = ToolRegistry()
    for n in names:
        reg.register(n, f"{n} tool", {"type": "object", "properties": {}})(lambda **kwargs: "ok")
    return reg


@pytest.mark.asyncio
async def test_sync_sub_agent_inherits_parent_channel(monkeypatch: pytest.MonkeyPatch):
    async def fake_confirm(name, args, origin=None):
        return True

    async def fake_ask(*args):
        return "yes"

    parent = AgentContext(
        workspace=Path.cwd(),
        tool_registry=_fake_registry(["read", "ask_question"]),
        confirm_callback=fake_confirm,
        ask_callback=fake_ask,
    )
    parent.metadata["session_id"] = "s1"

    async def fake_get_agent(name):
        return {
            "name": "coder",
            "display_name": "代码专家",
            "role": "r",
            "goal": "g",
            "model": "",
            "allow_delegation": False,
            "tool_permissions": {},
        }

    captured = {}

    async def fake_run_agent(sub_ctx, task):
        captured["ctx"] = sub_ctx

    monkeypatch.setattr(agents_module, "get_agent", fake_get_agent)
    monkeypatch.setattr(agents_module, "_classify_task", lambda task: "code")
    monkeypatch.setattr(agents_module, "inject_agent_lessons", _async_return("prompt"))
    monkeypatch.setattr(agents_module, "_load_shared_context", _async_return(""))
    monkeypatch.setattr("crabagent.core.agent.loop.run_agent", fake_run_agent)

    await agents_module.spawn_sub_agent("coder", "do it", parent, background=False)

    sub = captured["ctx"]
    assert sub.confirm_callback is fake_confirm
    assert sub.ask_callback is fake_ask
    origin = sub.metadata["_agent_origin"]
    assert origin["agent_name"] == "coder"
    assert origin["display_name"] == "代码专家"
    assert origin["sub_agent_id"].startswith("coder_")


@pytest.mark.asyncio
async def test_background_sub_agent_gets_no_channel(monkeypatch: pytest.MonkeyPatch):
    async def fake_confirm(name, args, origin=None):
        return True

    parent = AgentContext(workspace=Path.cwd(), tool_registry=_fake_registry(["read"]), confirm_callback=fake_confirm)
    parent.metadata["session_id"] = "s1"

    async def fake_get_agent(name):
        return {
            "name": "researcher",
            "display_name": "研究员",
            "role": "r",
            "goal": "g",
            "model": "",
            "allow_delegation": False,
            "tool_permissions": {},
        }

    captured = {}

    async def fake_run_agent(sub_ctx, task):
        captured["ctx"] = sub_ctx

    monkeypatch.setattr(agents_module, "get_agent", fake_get_agent)
    monkeypatch.setattr(agents_module, "_classify_task", lambda task: "research")
    monkeypatch.setattr(agents_module, "inject_agent_lessons", _async_return("prompt"))
    monkeypatch.setattr(agents_module, "_load_shared_context", _async_return(""))
    monkeypatch.setattr("crabagent.core.agent.loop.run_agent", fake_run_agent)

    await agents_module.spawn_sub_agent("researcher", "research it", parent, background=True)

    sub = captured["ctx"]
    assert sub.confirm_callback is None
    assert sub.ask_callback is None
    # Origin is still recorded for logging/attribution.
    assert sub.metadata["_agent_origin"]["agent_name"] == "researcher"


def test_ask_question_not_withheld_from_sub_agents():
    assert "ask_question" not in agents_module._DELEGATION_TOOLS
    assert "delegate_task" in agents_module._DELEGATION_TOOLS


async def _async_str(value):
    return value


# ── update_goal narrowing ────────────────────────────────────────────────────


def _fake_db(goal):
    class FakeSession:
        committed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            self.committed = True

    return FakeSession(), goal


@pytest.mark.asyncio
async def test_update_goal_tool_schema_only_exposes_terminal_statuses():
    context = AgentContext(workspace=Path.cwd(), tool_registry=ToolRegistry())
    goal_tools.register_goal_tools(context, "session", 1)
    tool = context.tool_registry.get("update_goal")
    enum = tool.parameters["properties"]["status"]["enum"]
    assert enum == ["complete", "unmet"]


@pytest.mark.asyncio
async def test_update_goal_rejects_paused_from_agent(monkeypatch: pytest.MonkeyPatch):
    context = AgentContext(workspace=Path.cwd(), tool_registry=ToolRegistry())
    goal_tools.register_goal_tools(context, "session", 1)
    handler = context.tool_registry.get("update_goal").handler

    session, goal = _fake_db(SimpleNamespace(auto_turns=3, auto_continue=True))
    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: session)

    called = []

    async def fake_update(*a, **k):
        called.append(k)

    monkeypatch.setattr(goal_tools, "update_goal", fake_update)
    result = await handler(status="paused", context=context)
    assert result.startswith("Error:")
    assert "user action" in result
    assert called == []
    # Not marked as finalised → the run-finalization checkpoint still fires.
    assert "_goal_status_updated" not in context.metadata


@pytest.mark.asyncio
async def test_update_goal_blocks_early_unmet_on_auto_continue(monkeypatch: pytest.MonkeyPatch):
    context = AgentContext(workspace=Path.cwd(), tool_registry=ToolRegistry())
    goal_tools.register_goal_tools(context, "session", 1)
    handler = context.tool_registry.get("update_goal").handler

    session, goal = _fake_db(SimpleNamespace(auto_turns=1, auto_continue=True))
    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: session)

    async def fake_current(_db, session_id):
        return goal

    called = []

    async def fake_update(*a, **k):
        called.append(k)

    monkeypatch.setattr(goal_tools, "get_current_goal", fake_current)
    monkeypatch.setattr(goal_tools, "update_goal", fake_update)

    result = await handler(status="unmet", blocker="stuck", context=context)
    assert result.startswith("Error:")
    assert "ask_question" in result
    assert called == []


@pytest.mark.asyncio
async def test_update_goal_allows_unmet_after_enough_turns(monkeypatch: pytest.MonkeyPatch):
    context = AgentContext(workspace=Path.cwd(), tool_registry=ToolRegistry())
    goal_tools.register_goal_tools(context, "session", 1)
    handler = context.tool_registry.get("update_goal").handler

    goal = SimpleNamespace(auto_turns=3, auto_continue=True)
    session, _ = _fake_db(goal)
    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: session)

    async def fake_current(_db, session_id):
        return goal

    called = []

    async def fake_update(_db, g, **k):
        called.append(k)
        g.status = k["status"]

    monkeypatch.setattr(goal_tools, "get_current_goal", fake_current)
    monkeypatch.setattr(goal_tools, "update_goal", fake_update)
    monkeypatch.setattr(goal_tools, "goal_to_dict", lambda g: {"status": g.status})

    emitted = []

    async def fake_emit(event):
        emitted.append(event)

    context.event_bus.emit = fake_emit
    result = await handler(status="unmet", blocker="real blocker", context=context)
    assert result == {"goal": {"status": "unmet"}}
    assert called and called[0]["status"] == "unmet"
    assert context.metadata["_goal_status_updated"] is True
    assert emitted and emitted[0].type == "goal_status_changed"


@pytest.mark.asyncio
async def test_update_goal_unmet_guard_skipped_when_not_auto_continue(monkeypatch: pytest.MonkeyPatch):
    """A manually driven goal (auto_continue=False) may be declared unmet on turn 0."""
    context = AgentContext(workspace=Path.cwd(), tool_registry=ToolRegistry())
    goal_tools.register_goal_tools(context, "session", 1)
    handler = context.tool_registry.get("update_goal").handler

    goal = SimpleNamespace(auto_turns=0, auto_continue=False)
    session, _ = _fake_db(goal)
    monkeypatch.setattr("crabagent.core.database.async_session_factory", lambda: session)

    async def fake_current(_db, session_id):
        return goal

    async def fake_update(_db, g, **k):
        g.status = k["status"]

    monkeypatch.setattr(goal_tools, "get_current_goal", fake_current)
    monkeypatch.setattr(goal_tools, "update_goal", fake_update)
    monkeypatch.setattr(goal_tools, "goal_to_dict", lambda g: {"status": g.status})
    context.event_bus.emit = _fake_emit
    result = await handler(status="unmet", blocker="b", context=context)
    assert result == {"goal": {"status": "unmet"}}


async def _fake_emit(event):
    return None


# ── Continuation prompt & goal prompt ────────────────────────────────────────


def test_goal_continuation_message_demands_evidence_audit():
    from crabagent.serve.api.prompt import PromptRequest, _goal_continuation_request

    req = _goal_continuation_request(PromptRequest(message="x"))
    msg = req.message
    assert "evidence" in msg
    assert "success criterion" in msg
    assert "update_goal" in msg
    assert "ask_question" in msg
    # Not a bare "continue".
    assert not msg.lower().startswith("continue the active goal from the latest checkpoint")


def test_goal_prompt_forbids_agent_pause_and_requires_evidence_mapping():
    from crabagent.core.goals.service import goal_prompt

    goal = SimpleNamespace(
        objective="Ship it",
        success_criteria=["tests pass"],
        constraints=[],
        latest_checkpoint="",
    )
    text = goal_prompt(goal)
    assert 'complete" or unmet' in text or "complete or unmet" in text or "complete\n" in text or "complete " in text
    assert "Do not pause or resume" in text
    assert "concrete evidence" in text
    assert "ask_question" in text
    assert "paused, or unmet" not in text


# ── serve-layer origin plumbing ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_confirmation_emits_and_persists_origin(monkeypatch: pytest.MonkeyPatch):
    from crabagent.serve.api import confirm as confirm_api

    confirm_api._pending_confirms.clear()
    persisted = {}
    created = {}

    async def fake_persist(session_id, confirm_id, tool_name, args_summary, origin=None):
        persisted["origin"] = origin

    class FakeDB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def fake_create(db, **kwargs):
        created.update(kwargs)

    monkeypatch.setattr(confirm_api, "_persist_confirmation", fake_persist)
    monkeypatch.setattr("crabagent.core.database.async_session_factory", FakeDB)
    monkeypatch.setattr("crabagent.core.task.request_service.create_request", fake_create)
    monkeypatch.setattr("crabagent.core.task.request_service.register_live_future", lambda *a, **k: None)
    monkeypatch.setattr(
        "crabagent.core.push.notify_request_created",
        lambda **kwargs: _async_str(None),
    )

    emitted = []

    class FakeBus:
        async def emit(self, event):
            emitted.append(event)

    origin = {"agent_name": "coder", "display_name": "代码专家", "sub_agent_id": "coder_abc"}
    fut = await confirm_api.request_confirmation(FakeBus(), "s1", "bash", {"command": "ls"}, user_id=1, origin=origin)

    assert not fut.done()
    assert emitted[0].data["origin"] == origin
    assert persisted["origin"] == origin
    assert "代码专家" in created["title"]
    assert created["display_payload"]["origin"] == origin
    entry = next(iter(confirm_api._pending_confirms.values()))
    assert len(entry) == 5 and entry[4] == origin
    confirm_api._pending_confirms.clear()


@pytest.mark.asyncio
async def test_request_confirmation_without_origin_omits_field(monkeypatch: pytest.MonkeyPatch):
    from crabagent.serve.api import confirm as confirm_api

    confirm_api._pending_confirms.clear()

    async def fake_persist(*a, **k):
        return None

    class FakeDB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def fake_create(db, **kwargs):
        return None

    monkeypatch.setattr(confirm_api, "_persist_confirmation", fake_persist)
    monkeypatch.setattr("crabagent.core.database.async_session_factory", FakeDB)
    monkeypatch.setattr("crabagent.core.task.request_service.create_request", fake_create)
    monkeypatch.setattr("crabagent.core.task.request_service.register_live_future", lambda *a, **k: None)
    monkeypatch.setattr("crabagent.core.push.notify_request_created", lambda **kwargs: _async_str(None))

    emitted = []

    class FakeBus:
        async def emit(self, event):
            emitted.append(event)

    await confirm_api.request_confirmation(FakeBus(), "s1", "bash", {"command": "ls"}, user_id=1)
    assert "origin" not in emitted[0].data
    assert confirm_api.get_pending_confirms_for_session("s1")[0].get("origin") is None
    confirm_api._pending_confirms.clear()


@pytest.mark.asyncio
async def test_request_user_input_forwards_recommended_header_origin(monkeypatch: pytest.MonkeyPatch):
    from crabagent.serve.api import input as input_api

    input_api._pending_inputs.clear()
    created = {}

    class FakeDB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def fake_create(db, **kwargs):
        created.update(kwargs)

    monkeypatch.setattr("crabagent.core.database.async_session_factory", FakeDB)
    monkeypatch.setattr("crabagent.core.task.request_service.create_request", fake_create)
    monkeypatch.setattr("crabagent.core.task.request_service.register_live_future", lambda *a, **k: None)
    monkeypatch.setattr("crabagent.core.push.notify_request_created", lambda **kwargs: _async_str(None))

    emitted = []

    class FakeBus:
        async def emit(self, event):
            emitted.append(event)

    origin = {"agent_name": "coder", "display_name": "x", "sub_agent_id": "s"}
    await input_api.request_user_input(
        FakeBus(),
        "s1",
        "Which?",
        options=["A", "B"],
        recommended="A",
        header="策略",
        origin=origin,
    )
    data = emitted[0].data
    assert data["recommended"] == "A"
    assert data["header"] == "策略"
    assert data["origin"] == origin
    assert created["title"].startswith("策略 · ")
    assert created["display_payload"] == {"recommended": "A", "header": "策略", "origin": origin}
    input_api._pending_inputs.clear()


@pytest.mark.asyncio
async def test_request_user_input_drops_recommended_not_in_options(monkeypatch: pytest.MonkeyPatch):
    from crabagent.serve.api import input as input_api

    input_api._pending_inputs.clear()

    class FakeDB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def fake_create(db, **kwargs):
        return None

    monkeypatch.setattr("crabagent.core.database.async_session_factory", FakeDB)
    monkeypatch.setattr("crabagent.core.task.request_service.create_request", fake_create)
    monkeypatch.setattr("crabagent.core.task.request_service.register_live_future", lambda *a, **k: None)
    monkeypatch.setattr("crabagent.core.push.notify_request_created", lambda **kwargs: _async_str(None))

    emitted = []

    class FakeBus:
        async def emit(self, event):
            emitted.append(event)

    await input_api.request_user_input(FakeBus(), "s1", "Which?", options=["A", "B"], recommended="Z")
    assert "recommended" not in emitted[0].data
    input_api._pending_inputs.clear()


# ── Signature sanity ─────────────────────────────────────────────────────────


def test_request_user_input_signature_exposes_new_fields():
    from crabagent.serve.api.input import request_user_input

    params = inspect.signature(request_user_input).parameters
    for name in ("recommended", "header", "origin"):
        assert name in params, name


@pytest.mark.asyncio
async def test_registry_confirm_route_passes_sub_agent_origin():
    """End-to-end: a confirmation-gated tool executed under a sub-agent context
    must hand the sub-agent's origin to the parent's confirm callback."""
    registry = ToolRegistry()

    @registry.register(
        name="gated",
        description="g",
        parameters={"type": "object", "properties": {}},
        requires_permission=True,
    )
    async def gated(context=None):
        return "ok"

    seen = {}

    async def parent_confirm(tool_name, args, origin=None):
        seen["origin"] = origin
        return True

    sub = AgentContext(workspace=Path.cwd(), confirm_callback=parent_confirm)
    sub.metadata["_agent_origin"] = {"agent_name": "coder", "display_name": "代码专家", "sub_agent_id": "coder_x"}
    result = await registry.execute("gated", {}, context=sub)
    assert result == "ok"
    assert seen["origin"]["display_name"] == "代码专家"

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from crabagent.core.agent.tools import computer
from crabagent.core.computer.session import ComputerSession


def context(confirm=None):
    return SimpleNamespace(
        metadata={"_collab_browser_observation_id": "obs", "_collab_browser_page_version": 1}, confirm_callback=confirm
    )


@pytest.mark.asyncio
async def test_observe_returns_image_and_metadata(monkeypatch):
    monkeypatch.setattr(
        computer,
        "_bridge_request",
        lambda *_, **kwargs: {
            "observation_id": "new",
            "page_version": 2,
            "data_url": "data:image/jpeg;base64,AA",
            "mime": "image/jpeg",
        },
    )
    ctx = context()
    result = await computer.computer_observe(context=ctx)
    assert result[1]["type"] == "image_url"
    assert ctx.metadata["_collab_browser_observation_id"] == "new"
    assert "data_url" not in result[0]["text"]


@pytest.mark.asyncio
async def test_point_click_confirmation_is_per_action(monkeypatch):
    commands = []

    def bridge(command, payload=None, **kwargs):
        commands.append(command)
        if command == "point":
            return {"confirmation_required": True, "pending_action_id": "ticket", "label": "Delete"}
        return {"performed": "click"}

    monkeypatch.setattr(computer, "_bridge_request", bridge)

    async def approve(_name, _args):
        return True

    result = json.loads(
        await computer.computer_act("obs", [{"type": "click_point", "x": 10, "y": 10}], context(approve))
    )
    assert result["actions"][0]["status"] == "executed"
    assert commands == ["point", "commit_point"]


@pytest.mark.asyncio
async def test_unapproved_point_stops_batch(monkeypatch):
    calls = []

    def bridge(command, payload=None, **kwargs):
        calls.append(command)
        return {"confirmation_required": True, "pending_action_id": "ticket"}

    monkeypatch.setattr(computer, "_bridge_request", bridge)
    actions = [{"type": "click_point", "x": 10, "y": 10}, {"type": "move", "x": 20, "y": 20}]
    result = json.loads(await computer.computer_act("obs", actions, context()))
    assert [item["status"] for item in result["actions"]] == ["blocked", "not_executed"]
    assert calls == ["point"]


@pytest.mark.asyncio
async def test_stale_and_budget_rejected_without_bridge(monkeypatch):
    monkeypatch.setattr(computer, "_bridge_request", lambda *_, **kwargs: pytest.fail("bridge must not be reached"))
    ctx = context()
    with pytest.raises(RuntimeError, match="STALE_OBSERVATION"):
        await computer.computer_act("old", [{"type": "move", "x": 1, "y": 1}], ctx)
    ctx.metadata["_computer_session"] = ComputerSession(actions=60)
    with pytest.raises(RuntimeError, match="BUDGET_EXCEEDED"):
        await computer.computer_act("obs", [{"type": "move", "x": 1, "y": 1}], ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["move", "scroll", "wait"])
async def test_batch_never_reuses_observation_after_first_action(monkeypatch, first):
    calls = []

    def bridge(command, payload=None, **kwargs):
        calls.append(command)
        return {"performed": first}

    monkeypatch.setattr(computer, "_bridge_request", bridge)
    actions = [{"type": first, "x": 10, "y": 10, "amount": 40}, {"type": "keypress", "key": "Tab"}]
    result = json.loads(await computer.computer_act("obs", actions, context()))
    assert len(calls) == 1
    assert [item["status"] for item in result["actions"]] == ["executed", "not_executed"]


@pytest.mark.asyncio
async def test_action_invalidates_python_observation(monkeypatch):
    calls = []

    def bridge(command, payload=None, **kwargs):
        calls.append(command)
        return {"performed": "move"}

    monkeypatch.setattr(computer, "_bridge_request", bridge)
    ctx = context()
    await computer.computer_act("obs", [{"type": "move", "x": 10, "y": 10}], ctx)
    assert "_collab_browser_observation_id" not in ctx.metadata
    with pytest.raises(RuntimeError, match="STALE_OBSERVATION"):
        await computer.computer_act("obs", [{"type": "move", "x": 10, "y": 10}], ctx)
    assert calls == ["point"]

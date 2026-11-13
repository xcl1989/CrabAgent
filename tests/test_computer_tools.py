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
async def test_observe_rejects_empty_data_url(monkeypatch):
    monkeypatch.setattr(
        computer,
        "_bridge_request",
        lambda *_, **kwargs: {
            "observation_id": "new",
            "page_version": 2,
            "data_url": "data:image/jpeg;base64,",
            "mime": "image/jpeg",
        },
    )
    ctx = context()

    with pytest.raises(RuntimeError, match="CAPTURE_FAILED"):
        await computer.computer_observe(context=ctx)


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


def batch_snapshot():
    return {
        "url": "https://example.test/",
        "page_version": 1,
        "viewport": {"width": 800, "height": 600, "scrollY": 0},
        "elements": [
            {
                "index": i,
                "fingerprint": f"INPUT|text|field{i}",
                "bounds": {"x": i * 20},
                "tag": "input",
                "type": "text",
                "sensitive": False,
            }
            for i in (1, 2, 3)
        ],
    }


@pytest.mark.asyncio
async def test_independent_fields_are_refreshed_between_actions(monkeypatch):
    calls = []

    def bridge(command, payload=None, **kwargs):
        calls.append((command, payload))
        if command == "observe":
            return {**batch_snapshot(), "observation_id": "fresh"}
        return {"typed": payload["index"]}

    monkeypatch.setattr(computer, "_bridge_request", bridge)
    ctx = context()
    ctx.metadata["_computer_batch_snapshot"] = batch_snapshot()
    result = json.loads(
        await computer.computer_act(
            "obs",
            [
                {"type": "type_text", "index": 1, "text": "a"},
                {"type": "type_text", "index": 2, "text": "b"},
            ],
            ctx,
        )
    )
    assert [a["status"] for a in result["actions"]] == ["executed", "executed"]
    assert [c[0] for c in calls] == ["type", "observe", "type"]
    assert calls[-1][1]["observation_id"] == "fresh"
    assert "_collab_browser_observation_id" not in ctx.metadata


@pytest.mark.asyncio
async def test_batch_stops_when_field_changes(monkeypatch):
    calls = []

    def bridge(command, payload=None, **kwargs):
        calls.append(command)
        if command == "observe":
            snapshot = batch_snapshot()
            snapshot["elements"][1]["fingerprint"] = "changed"
            return {**snapshot, "observation_id": "fresh"}
        return {"typed": 1}

    monkeypatch.setattr(computer, "_bridge_request", bridge)
    ctx = context()
    ctx.metadata["_computer_batch_snapshot"] = batch_snapshot()
    result = json.loads(
        await computer.computer_act(
            "obs",
            [
                {"type": "type_text", "index": 1, "text": "a"},
                {"type": "type_text", "index": 2, "text": "b"},
            ],
            ctx,
        )
    )
    assert [a["status"] for a in result["actions"]] == ["executed", "not_executed"]
    assert calls == ["type", "observe"]


@pytest.mark.asyncio
async def test_hold_game_keys_consumes_observation_and_dispatches(monkeypatch):
    calls = []

    def bridge(command, payload=None, **kwargs):
        calls.append((command, payload))
        return {"released": True}

    monkeypatch.setattr(computer, "_bridge_request", bridge)
    ctx = context()
    result = json.loads(await computer.computer_hold_game_keys("obs", ["KeyW", "ArrowRight"], 100, ctx))
    assert result["released"] and result["needs_observation"]
    assert calls[0][0] == "hold_game_keys"
    assert "_collab_browser_observation_id" not in ctx.metadata


@pytest.mark.asyncio
async def test_hold_game_keys_rejects_invalid_and_stale(monkeypatch):
    monkeypatch.setattr(computer, "_bridge_request", lambda *a, **k: pytest.fail("bridge reached"))
    with pytest.raises(ValueError):
        await computer.computer_hold_game_keys("obs", ["Command"], 100, context())
    with pytest.raises(RuntimeError, match="STALE_OBSERVATION"):
        await computer.computer_hold_game_keys("old", ["KeyW"], 100, context())

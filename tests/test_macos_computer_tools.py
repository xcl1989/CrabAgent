"""M1 tests for the macOS computer-use Python tools."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from crabagent.core.agent.tools import macos_computer


def context():
    metadata: dict = {"_macos_input_confirmed": True}
    return SimpleNamespace(metadata=metadata, confirm_callback=None)


def fresh_context():
    ctx = context()
    ctx.metadata.pop("_macos_input_confirmed")
    return ctx


@pytest.mark.asyncio
async def test_windows_lists_and_records(monkeypatch):
    seen = {}

    async def bridge(command, payload, context=None):
        seen["command"] = command
        return {"ok": True, "windows": [{"windowId": 1, "pid": 2, "bundleId": "com.apple.TextEdit"}]}

    monkeypatch.setattr(macos_computer, "_call_bridge", bridge)
    result = json.loads(await macos_computer.macos_windows(context=context()))
    assert result["windows"][0]["bundleId"] == "com.apple.TextEdit"
    assert seen["command"] == "macos_windows"


@pytest.mark.asyncio
async def test_observe_relays_window(monkeypatch):
    captured = {}

    async def bridge(command, payload, context=None):
        captured.update(command=command, payload=payload)
        return {"ok": True, "nodes": [{"role": "AXWindow"}]}

    monkeypatch.setattr(macos_computer, "_call_bridge", bridge)
    result = json.loads(await macos_computer.macos_observe(7, 42, context=context()))
    assert captured == {"command": "macos_observe", "payload": {"windowId": 7, "pid": 42}}
    assert result["nodes"][0]["role"] == "AXWindow"


@pytest.mark.asyncio
async def test_capture_returns_image_result(monkeypatch):
    async def bridge(command, payload, context=None):
        assert command == "macos_capture" and payload == {"windowId": 7}
        return {"ok": True, "windowId": 7, "dataUrl": "data:image/jpeg;base64,QQ", "mime": "image/jpeg"}

    monkeypatch.setattr(macos_computer, "_call_bridge", bridge)
    result = await macos_computer.macos_capture(7, context=context())
    assert result[1]["image_url"]["url"] == "data:image/jpeg;base64,QQ"
    assert "dataUrl" not in result[0]["text"]


@pytest.mark.asyncio
async def test_input_requires_prior_observation(monkeypatch):
    monkeypatch.setattr(macos_computer, "_call_bridge", lambda *a, **k: pytest.fail("bridge reached"))
    with pytest.raises(RuntimeError, match="STALE_OBSERVATION"):
        await macos_computer.macos_click(7, 42, 10, 10, context=fresh_context())


@pytest.mark.asyncio
async def test_click_passes_window_and_coords(monkeypatch):
    captured = {}

    async def bridge(command, payload, context=None):
        captured.update(command=command, payload=payload)
        return {"ok": True, "clicked": {"x": 10, "y": 10}}

    monkeypatch.setattr(macos_computer, "_call_bridge", bridge)
    ctx = context()
    await macos_computer.macos_click(7, 42, 10, 10, context=ctx)
    assert captured["command"] == "macos_click"
    assert captured["payload"] == {"windowId": 7, "pid": 42, "x": 10, "y": 10}


@pytest.mark.asyncio
async def test_type_truncates_and_scroll_clamps(monkeypatch):
    captured = []

    async def bridge(command, payload, context=None):
        captured.append((command, payload))
        return {"ok": True}

    monkeypatch.setattr(macos_computer, "_call_bridge", bridge)
    await macos_computer.macos_type(7, "中" * 9000, context=context())
    await macos_computer.macos_scroll(7, 99999, context=context())
    assert captured[0][1]["text"] == "中" * 9000
    assert len(captured[0][1]["text"]) == 9000
    assert captured[1][1]["amount"] == 2000


@pytest.mark.asyncio
async def test_failure_counts_budget_and_reraises(monkeypatch):
    async def bridge(command, payload, context=None):
        raise RuntimeError("permission denied: accessibility not granted")

    monkeypatch.setattr(macos_computer, "_call_bridge", bridge)
    ctx = context()
    with pytest.raises(RuntimeError, match="permission denied"):
        await macos_computer.macos_observe(7, 42, context=ctx)
    assert ctx.metadata["_computer_session"].failures == 1


@pytest.mark.asyncio
async def test_allow_flow_adds_app_and_retries(monkeypatch):
    calls = []

    async def bridge(command, payload, context=None):
        calls.append((command, payload))
        if command == "macos_click":
            click_count = len([c for c in calls if c[0] == "macos_click"])
            if click_count == 1:
                return {"ok": False, "error": "precondition failed: APP_NOT_ALLOWLISTED: com.apple.TextEdit"}
            return {"ok": True, "clicked": {"x": 10, "y": 10}}
        return {"ok": True}

    monkeypatch.setattr(macos_computer, "_call_bridge", bridge)

    async def approve(_name, args):
        assert args["bundleId"] == "com.apple.TextEdit"
        return True

    ctx = context()
    ctx.confirm_callback = approve
    result = json.loads(await macos_computer.macos_click(7, 42, 10, 10, context=ctx))
    assert result["clicked"] == {"x": 10, "y": 10}
    assert result["clicked"] == {"x": 10, "y": 10}
    assert [c for c, _ in calls] == ["macos_click", "macos_allow_app", "macos_click"]
    assert calls[1][1] == {"bundleId": "com.apple.TextEdit"}


@pytest.mark.asyncio
async def test_allow_flow_denial_blocks_without_retry(monkeypatch):
    calls = []

    async def bridge(command, payload, context=None):
        calls.append(command)
        if command == "macos_click":
            return {"ok": False, "error": "precondition failed: APP_NOT_ALLOWLISTED: com.apple.Calc"}
        return {"ok": True}

    monkeypatch.setattr(macos_computer, "_call_bridge", bridge)

    async def deny(_name, _args):
        return False

    ctx = context()
    result = json.loads(await macos_computer.macos_click(7, 42, 10, 10, context=ctx))
    assert result["status"] == "blocked"
    assert calls == ["macos_click"]


@pytest.mark.asyncio
async def test_allow_flow_without_callback_blocks(monkeypatch):
    async def bridge(command, payload, context=None):
        if command == "macos_click":
            return {"ok": False, "error": "precondition failed: APP_NOT_ALLOWLISTED: com.apple.Calc"}
        return {"ok": True}

    monkeypatch.setattr(macos_computer, "_call_bridge", bridge)
    result = json.loads(await macos_computer.macos_click(7, 42, 10, 10, context=context()))
    assert result["status"] == "blocked"


@pytest.mark.asyncio
async def test_observe_sets_input_precondition(monkeypatch):
    async def bridge(command, payload, context=None):
        assert command == "macos_observe"
        return {"ok": True, "nodes": [{"role": "AXWindow"}]}

    monkeypatch.setattr(macos_computer, "_call_bridge", bridge)
    ctx = fresh_context()
    await macos_computer.macos_observe(7, 42, context=ctx)
    assert ctx.metadata["_macos_input_confirmed"] is True


@pytest.mark.asyncio
async def test_capture_sets_input_precondition(monkeypatch):
    async def bridge(command, payload, context=None):
        assert command == "macos_capture"
        return {"ok": True, "windowId": 7, "dataUrl": "data:image/jpeg;base64,QQ"}

    monkeypatch.setattr(macos_computer, "_call_bridge", bridge)
    ctx = fresh_context()
    await macos_computer.macos_capture(7, context=ctx)
    assert ctx.metadata["_macos_input_confirmed"] is True

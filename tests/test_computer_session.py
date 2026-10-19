import asyncio
from types import SimpleNamespace

import pytest

from crabagent.core.agent.tools import computer, macos_computer
from crabagent.core.computer import session as module


@pytest.fixture
def clock(monkeypatch):
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(module.time, "monotonic", lambda: clock.now)
    return clock


def test_idle_time_is_not_active_time(clock):
    session = module.ComputerSession()
    clock.now = 1200
    session.check()
    with session.track():
        clock.now += 5
    clock.now += 1000
    session.check()
    assert session.active_seconds == 5


def test_overlap_is_counted_once(clock):
    session = module.ComputerSession()
    with session.track():
        clock.now = 3
        with session.track():
            clock.now = 7
            assert session.active_seconds == 7
        clock.now = 10
    assert session.active == 10


@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
def test_failure_and_cancellation_are_counted(clock, error):
    session = module.ComputerSession()
    with pytest.raises(error):
        with session.track():
            clock.now = 8
            raise error()
    assert session.active == 8
    assert session._tracking == 0


def test_active_limit_checked_during_call(clock):
    session = module.ComputerSession()
    with session.track():
        clock.now = 900
        with pytest.raises(RuntimeError, match="task timed out"):
            session.check()


def test_wall_clock_expiry(clock):
    session = module.ComputerSession()
    clock.now = 3600
    with pytest.raises(RuntimeError, match="task expired"):
        session.check()


@pytest.mark.asyncio
async def test_browser_confirmation_wait_is_excluded(clock, monkeypatch):
    ctx = SimpleNamespace(metadata={"_collab_browser_observation_id": "obs", "_collab_browser_page_version": 1})

    async def approve(*args):
        clock.now += 1200
        return True

    def bridge(command, *args, **kwargs):
        clock.now += 2
        if command == "point":
            return {"confirmation_required": True, "pending_action_id": "ticket"}
        return {"status": "executed"}

    ctx.confirm_callback = approve
    monkeypatch.setattr(computer, "_bridge_request", bridge)
    await computer.computer_act("obs", [{"type": "click_point", "x": 1, "y": 1}], ctx)
    assert ctx.metadata["_computer_session"].active == 4


@pytest.mark.asyncio
async def test_macos_confirmation_wait_is_excluded(clock, monkeypatch):
    ctx = SimpleNamespace(metadata={})
    calls = []

    async def approve(*args):
        clock.now += 1200
        return True

    def bridge(command, *args, **kwargs):
        calls.append(command)
        clock.now += 2
        if len(calls) == 1:
            return {"error": "APP_NOT_ALLOWLISTED: com.example.app"}
        return {"ok": True}

    ctx.confirm_callback = approve
    monkeypatch.setattr(macos_computer, "_bridge_request", bridge)
    await macos_computer._input_with_allow_flow("macos_activate", {}, ctx, "macos_activate", 0)
    assert ctx.metadata["_computer_session"].active == 6


@pytest.mark.asyncio
async def test_confirmation_rechecks_expiry_before_commit(clock, monkeypatch):
    calls = []
    ctx = SimpleNamespace(metadata={"_collab_browser_observation_id": "obs", "_collab_browser_page_version": 1})

    async def approve(*args):
        clock.now = 3600
        return True

    def bridge(command, *args, **kwargs):
        calls.append(command)
        return {"confirmation_required": True, "pending_action_id": "ticket"}

    ctx.confirm_callback = approve
    monkeypatch.setattr(computer, "_bridge_request", bridge)
    result = await computer.computer_act("obs", [{"type": "click_point", "x": 1, "y": 1}], ctx)
    assert "task expired" in result
    assert calls == ["point"]

"""Tests for WeChatMessageLoop self-heal (consecutive poll error rebuild)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from crabagent.core.wechat.client import IncomingMessage
from crabagent.core.wechat.message import (
    _MAX_CONSECUTIVE_POLL_ERRORS,
    WeChatMessageLoop,
)


def _make_loop(client, **kwargs) -> WeChatMessageLoop:
    return WeChatMessageLoop(client, **kwargs)


@pytest.fixture
def flaky_client():
    """Client whose get_updates always raises, send/db helpers mocked out."""
    client = AsyncMock()
    client.get_updates = AsyncMock(side_effect=RuntimeError("boom"))
    return client


@pytest.mark.asyncio
async def test_loop_rebuilds_after_consecutive_errors(flaky_client, monkeypatch):
    """After _MAX_CONSECUTIVE_POLL_ERRORS consecutive errors the loop gives
    up, fires on_connection_lost, and stops itself."""
    monkeypatch.setattr("crabagent.core.wechat.message._ERROR_BACKOFF", 0.01)

    rebuilt = asyncio.Event()

    async def on_connection_lost():
        rebuilt.set()

    # Stop DB notification writes during the test
    async def _noop_notify(self):
        pass

    monkeypatch.setattr(WeChatMessageLoop, "_notify_connection_degraded", _noop_notify)

    loop = _make_loop(flaky_client, on_connection_lost=on_connection_lost)
    await loop.start()

    # Wait until the rebuild callback fires (with generous margin)
    await asyncio.wait_for(rebuilt.wait(), timeout=5.0)

    assert flaky_client.get_updates.await_count == _MAX_CONSECUTIVE_POLL_ERRORS
    assert loop._running is False
    await loop.stop()


@pytest.mark.asyncio
async def test_loop_resets_error_counter_on_success(flaky_client, monkeypatch):
    """A successful poll between errors resets the consecutive counter."""
    monkeypatch.setattr("crabagent.core.wechat.message._ERROR_BACKOFF", 0.01)

    ok_msg = IncomingMessage(
        msg_id="m1",
        from_user="u1",
        context_token="t1",
        content="",
        msg_type=1,
        attachments=[],
        get_updates_buf="buf1",
    )
    # fail (MAX-1) times, then succeed, then fail again → must NOT trigger rebuild
    flaky_client.get_updates.side_effect = (
        [RuntimeError("e")] * (_MAX_CONSECUTIVE_POLL_ERRORS - 1) + [[ok_msg]] + [RuntimeError("e")] * 50
    )

    async def on_connection_lost():
        raise AssertionError("should not rebuild — counter should reset on success")

    async def _noop_notify(self):
        pass

    monkeypatch.setattr(WeChatMessageLoop, "_notify_connection_degraded", _noop_notify)

    loop = _make_loop(flaky_client, on_connection_lost=on_connection_lost)
    await loop.start()
    # Run long enough to exceed MAX errors after the success
    await asyncio.sleep(0.01 * (_MAX_CONSECUTIVE_POLL_ERRORS + 6))
    await loop.stop()
    assert flaky_client.get_updates.await_count > _MAX_CONSECUTIVE_POLL_ERRORS


@pytest.mark.asyncio
async def test_session_expiry_stops_without_rebuild(flaky_client, monkeypatch):
    """SessionExpiredError still stops the loop directly (no rebuild callback)."""
    from crabagent.core.wechat.client import SessionExpiredError

    monkeypatch.setattr("crabagent.core.wechat.message._ERROR_BACKOFF", 0.01)
    flaky_client.get_updates.side_effect = SessionExpiredError("expired")

    async def on_connection_lost():
        raise AssertionError("session expiry must not fire connection-lost callback")

    async def _noop_notify(self):
        pass

    monkeypatch.setattr(WeChatMessageLoop, "_notify_session_expired", _noop_notify)

    loop = _make_loop(flaky_client, on_connection_lost=on_connection_lost)
    await loop.start()
    await asyncio.sleep(0.2)
    assert loop._running is False
    assert flaky_client.get_updates.await_count == 1

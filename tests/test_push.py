"""Tests for the push notification channel (Bark/ntfy).

Covers: config round-trip/masking, provider clients (with a fake httpx
transport), the PushNotification facade gating logic, and task-event
dedup/notify logic. DB-dependent code paths are exercised via monkeypatched
sessions where needed.
"""

from __future__ import annotations

import pytest

import crabagent.core.push as push_mod
from crabagent.core.push import PushNotification, notify_task_event
from crabagent.core.push.client import PushError, PushPayload, send_bark, send_ntfy
from crabagent.core.push.config import PushConfig

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestPushConfig:
    def test_defaults(self):
        cfg = PushConfig()
        assert cfg.enabled is False
        assert cfg.provider == "bark"
        assert cfg.bark_server == "https://api.day.app"

    def test_round_trip(self):
        cfg = PushConfig(enabled=True, provider="ntfy", ntfy_topic="abc", bark_device_key="key123")
        restored = PushConfig.from_dict(cfg.to_dict())
        assert restored == cfg

    def test_from_dict_ignores_unknown_fields(self):
        restored = PushConfig.from_dict({"provider": "ntfy", "nonexistent": 1})
        assert restored.provider == "ntfy"

    def test_masked_hides_secrets(self):
        cfg = PushConfig(bark_device_key="abcdefghijklmnop", ntfy_topic="topic-xyz")
        d = cfg.masked()
        assert d["bark_device_key"].startswith("•••")
        assert "abcdefghijklmnop" not in d["bark_device_key"]
        assert d["ntfy_topic"].startswith("•••")

    def test_masked_keeps_empty(self):
        d = PushConfig().masked()
        assert d["bark_device_key"] == ""
        assert d["ntfy_topic"] == ""


# ---------------------------------------------------------------------------
# Clients (fake httpx transport)
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, content_type="application/json"):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = str(self._json)
        self.headers = {"content-type": content_type}

    def json(self):
        return self._json


class FakeClient:
    """Stands in for httpx.AsyncClient; records the last request."""

    last_post = None

    def __init__(self, response=None, exc=None, **kwargs):
        self._response = response or FakeResponse()
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, content=None, headers=None):
        type(self).last_post = {"url": url, "json": json, "content": content, "headers": headers}
        if self._exc:
            raise self._exc
        return self._response


@pytest.fixture
def fake_http(monkeypatch):
    def _install(response=None, exc=None):
        resp = response or FakeResponse()

        class _Client:
            """Stands in for httpx.AsyncClient with canned behavior."""

            last_post = None

            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None, content=None, headers=None):
                type(self).last_post = {"url": url, "json": json, "content": content, "headers": headers}
                if exc:
                    raise exc
                return resp

        monkeypatch.setattr("crabagent.core.push.client.httpx.AsyncClient", _Client)
        return _Client

    return _install


@pytest.mark.asyncio
async def test_send_bark_ok(fake_http):
    cls = fake_http()
    payload = PushPayload(title="t", body="b", category="task_waiting", url="http://x")
    assert await send_bark("https://api.day.app", "KEY123", payload) is True
    req = cls.last_post
    assert req["url"] == "https://api.day.app/push"
    assert req["json"]["device_key"] == "KEY123"
    assert req["json"]["level"] == "timeSensitive"  # waiting is time-sensitive
    assert req["json"]["url"] == "http://x"


@pytest.mark.asyncio
async def test_send_bark_empty_key_raises(fake_http):
    fake_http()
    with pytest.raises(PushError):
        await send_bark("https://api.day.app", "", PushPayload(title="t"))


@pytest.mark.asyncio
async def test_send_bark_http_error(fake_http):
    fake_http(response=FakeResponse(status_code=403, json_data={"code": 403, "message": "bad key"}))
    with pytest.raises(PushError):
        await send_bark("https://api.day.app", "KEY", PushPayload(title="t"))


@pytest.mark.asyncio
async def test_send_bark_network_error(fake_http):
    fake_http(exc=httpx_connect_error())
    with pytest.raises(PushError):
        await send_bark("https://api.day.app", "KEY", PushPayload(title="t"))


def httpx_connect_error():
    import httpx

    return httpx.ConnectError("refused")


@pytest.mark.asyncio
async def test_send_ntfy_ok(fake_http):
    cls = fake_http(response=FakeResponse(status_code=200, json_data={}, content_type="text/plain"))
    payload = PushPayload(title="t", body="b", category="task_waiting", url="http://x")
    assert await send_ntfy("https://ntfy.sh", "topic1", payload) is True
    req = cls.last_post
    assert req["url"] == "https://ntfy.sh/topic1"
    assert req["headers"]["Click"] == "http://x"
    assert req["headers"]["Priority"] == "high"


@pytest.mark.asyncio
async def test_send_ntfy_empty_topic_raises(fake_http):
    fake_http()
    with pytest.raises(PushError):
        await send_ntfy("https://ntfy.sh", "", PushPayload(title="t"))


# ---------------------------------------------------------------------------
# Facade gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_facade_disabled_returns_false(monkeypatch):
    async def _cfg():
        return PushConfig(enabled=False, bark_device_key="k")

    monkeypatch.setattr(push_mod, "load_config", _cfg)
    called = []

    async def _send(*a, **kw):
        called.append(1)
        return True

    monkeypatch.setattr(push_mod, "send_bark", _send)
    assert await PushNotification.send("t") is False
    assert not called


@pytest.mark.asyncio
async def test_facade_category_toggle(monkeypatch):
    async def _cfg():
        return PushConfig(enabled=True, bark_device_key="k", notify_task_done=False)

    monkeypatch.setattr(push_mod, "load_config", _cfg)
    assert await PushNotification.send("t", category="task_done") is False


@pytest.mark.asyncio
async def test_facade_sends_via_provider(monkeypatch):
    async def _cfg():
        return PushConfig(enabled=True, provider="ntfy", ntfy_topic="tp", deep_link_base="http://ui")

    monkeypatch.setattr(push_mod, "load_config", _cfg)
    captured = {}

    async def _send(server, topic, payload):
        captured["server"], captured["topic"], captured["payload"] = server, topic, payload
        return True

    monkeypatch.setattr(push_mod, "send_ntfy", _send)
    ok = await PushNotification.send("T", "B", category="task_done")
    assert ok is True
    assert captured["topic"] == "tp"
    assert captured["payload"].url == "http://ui"  # deep link injected


@pytest.mark.asyncio
async def test_facade_provider_error_returns_false(monkeypatch):
    async def _cfg():
        return PushConfig(enabled=True, bark_device_key="k")

    monkeypatch.setattr(push_mod, "load_config", _cfg)

    async def _boom(*a, **kw):
        raise PushError("down")

    monkeypatch.setattr(push_mod, "send_bark", _boom)
    assert await PushNotification.send("t") is False


# ---------------------------------------------------------------------------
# Task event notify + dedup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_task_event_pushes_done(monkeypatch):
    pushed = []

    async def _fake_send(title, body="", url="", category=""):
        pushed.append((title, category))
        return True

    monkeypatch.setattr(PushNotification, "send", staticmethod(_fake_send))
    push_mod._recent.clear()
    notify_task_event("task_updated", {"task_id": "t1", "status": "done", "title": "X"})
    # let the scheduled task run
    import asyncio

    await asyncio.sleep(0.05)
    assert pushed and pushed[0][1] == "task_done"


@pytest.mark.asyncio
async def test_notify_task_event_dedup(monkeypatch):
    calls = []

    async def _fake_send(title, body="", url="", category=""):
        calls.append(1)
        return True

    monkeypatch.setattr(PushNotification, "send", staticmethod(_fake_send))
    push_mod._recent.clear()
    notify_task_event("task_updated", {"task_id": "t2", "status": "waiting_user", "title": "Y"})
    notify_task_event("task_updated", {"task_id": "t2", "status": "waiting_user", "title": "Y"})
    import asyncio

    await asyncio.sleep(0.05)
    assert len(calls) == 1  # second within window dropped


@pytest.mark.asyncio
async def test_notify_task_event_ignores_other_events(monkeypatch):
    calls = []

    async def _fake_send(title, body="", url="", category=""):
        calls.append(1)
        return True

    monkeypatch.setattr(PushNotification, "send", staticmethod(_fake_send))
    push_mod._recent.clear()
    notify_task_event("task_created", {"task_id": "t3", "status": "open"})
    import asyncio

    await asyncio.sleep(0.02)
    assert not calls

from __future__ import annotations

from types import SimpleNamespace

import pytest

from crabagent.core import proxy


class FakeRow:
    def __init__(self, value):
        self.value = value


class FakeResult:
    def __init__(self, row=None):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class FakeSession:
    def __init__(self, rows_by_key: dict[str, str | None]):
        self._rows = rows_by_key

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, statement):
        text = str(statement)
        for key, value in self._rows.items():
            if key in text:
                return FakeResult(FakeRow(value) if value is not None else None)
        return FakeResult(None)


def _patch_settings(monkeypatch: pytest.MonkeyPatch, rows: dict[str, str | None], web_proxy: str = ""):
    monkeypatch.setattr(proxy, "_get_setting", _async_lookup(rows))
    settings_obj = SimpleNamespace(web_proxy=web_proxy)
    monkeypatch.setattr("crabagent.core.config.settings", settings_obj)


@pytest.mark.asyncio
async def test_resolve_llm_proxy_returns_empty_without_opt_in():
    provider = SimpleNamespace(extra={})
    result = await proxy.resolve_llm_proxy(provider)
    assert result == ""


@pytest.mark.asyncio
async def test_resolve_llm_proxy_uses_provider_url(monkeypatch: pytest.MonkeyPatch):
    provider = SimpleNamespace(extra={"proxy_enabled": True, "proxy_url": "http://p:8080"})
    result = await proxy.resolve_llm_proxy(provider)
    assert result == "http://p:8080"


@pytest.mark.asyncio
async def test_resolve_llm_proxy_falls_back_to_global(monkeypatch: pytest.MonkeyPatch):
    _patch_settings(monkeypatch, {"llm_proxy": "http://global:1"})
    provider = SimpleNamespace(extra={"proxy_enabled": True, "proxy_url": ""})
    result = await proxy.resolve_llm_proxy(provider)
    assert result == "http://global:1"


@pytest.mark.asyncio
async def test_resolve_category_proxy_uses_category_specific(monkeypatch: pytest.MonkeyPatch):
    _patch_settings(monkeypatch, {"web_proxy": "http://web:2"})
    assert await proxy.resolve_category_proxy("web") == "http://web:2"


@pytest.mark.asyncio
async def test_resolve_category_proxy_falls_back_to_global_setting(monkeypatch: pytest.MonkeyPatch):
    _patch_settings(monkeypatch, {"proxy": "http://global:3"})
    assert await proxy.resolve_category_proxy("web") == "http://global:3"


@pytest.mark.asyncio
async def test_resolve_category_proxy_uses_env_fallback(monkeypatch: pytest.MonkeyPatch):
    _patch_settings(monkeypatch, {}, web_proxy="http://env:4")
    assert await proxy.resolve_category_proxy("web") == "http://env:4"


@pytest.mark.asyncio
async def test_get_httpx_kwargs_returns_empty_when_no_proxy(monkeypatch: pytest.MonkeyPatch):
    _patch_settings(monkeypatch, {})
    assert await proxy.get_httpx_kwargs("web") == {}


@pytest.mark.asyncio
async def test_get_httpx_kwargs_includes_proxy(monkeypatch: pytest.MonkeyPatch):
    _patch_settings(monkeypatch, {"web_proxy": "http://x:5"})
    assert await proxy.get_httpx_kwargs("web") == {"proxy": "http://x:5"}


def _async_lookup(rows: dict[str, str | None]):
    async def inner(key: str):
        return rows.get(key)

    return inner

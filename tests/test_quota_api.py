from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from crabagent.serve.api import quota as quota_api


@pytest.mark.asyncio
async def test_zhipu_standard_provider_rejects_coding_plan_quota(monkeypatch: pytest.MonkeyPatch):
    provider = SimpleNamespace(
        name="zhipu-org",
        provider_type="zhipu",
        api_key="org-key",
        base_url="https://open.bigmodel.cn/api/paas/v4",
    )

    async def fake_get_provider(name: str):
        assert name == "zhipu-org"
        return provider

    monkeypatch.setattr(quota_api, "get_provider", fake_get_provider)

    with pytest.raises(HTTPException) as exc_info:
        await quota_api.get_provider_quota(name="zhipu-org", user=SimpleNamespace(id=1))

    assert exc_info.value.status_code == 400
    assert "only available for personal Coding Plan" in exc_info.value.detail


@pytest.mark.asyncio
async def test_zhipu_coding_provider_queries_its_own_key(monkeypatch: pytest.MonkeyPatch):
    provider = SimpleNamespace(
        name="zhipu-personal",
        provider_type="zhipu",
        api_key="personal-key",
        base_url="https://open.bigmodel.cn/api/coding/paas/v4",
    )
    captured = {}

    async def fake_get_provider(name: str):
        assert name == "zhipu-personal"
        return provider

    async def fake_query(base_url: str, api_key: str):
        captured.update(base_url=base_url, api_key=api_key)
        return {"data": {"level": "pro", "limits": []}}

    monkeypatch.setattr(quota_api, "get_provider", fake_get_provider)
    monkeypatch.setattr(quota_api, "_query_zhipu_quota", fake_query)

    result = await quota_api.get_provider_quota(name="zhipu-personal", user=SimpleNamespace(id=1))

    assert captured == {
        "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
        "api_key": "personal-key",
    }
    assert result["summary"] == {"level": "pro", "token_limits": [], "time_limit": None}


@pytest.mark.asyncio
async def test_opencode_go_quota_uses_provider_key(monkeypatch: pytest.MonkeyPatch):
    provider = SimpleNamespace(provider_type="opencode-go", api_key="test-key")
    usage = {name: {"percent": 25, "status": "ok", "resetsAt": None} for name in ("rolling", "weekly", "monthly")}

    async def fake_get_provider(name):
        return provider

    async def fake_query(key):
        assert key == "test-key"
        return {"usage": usage}

    monkeypatch.setattr(quota_api, "get_provider", fake_get_provider)
    monkeypatch.setattr(quota_api, "_query_opencode_go_quota", fake_query)
    result = await quota_api.get_provider_quota(name="go", user=SimpleNamespace(id=1))
    assert result["summary"] == usage


@pytest.mark.asyncio
async def test_opencode_go_rejects_incomplete_usage(monkeypatch: pytest.MonkeyPatch):
    async def fake_get_provider(name):
        return SimpleNamespace(provider_type="opencode-go", api_key="test-key")

    async def fake_query(key):
        return {"usage": {}}

    monkeypatch.setattr(quota_api, "get_provider", fake_get_provider)
    monkeypatch.setattr(quota_api, "_query_opencode_go_quota", fake_query)
    with pytest.raises(HTTPException) as exc:
        await quota_api.get_provider_quota(name="go", user=SimpleNamespace(id=1))
    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_opencode_go_request_headers(monkeypatch: pytest.MonkeyPatch):
    import httpx

    def handler(request):
        assert str(request.url) == "https://opencode.ai/zen/go/v1/usage"
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.headers["user-agent"].startswith("crabagent")
        assert request.headers["x-opencode-session"]
        return httpx.Response(200, json={"usage": {}})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        quota_api.httpx, "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    assert await quota_api._query_opencode_go_quota("test-key") == {"usage": {}}

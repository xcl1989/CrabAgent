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

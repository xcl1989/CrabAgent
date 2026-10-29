from unittest.mock import AsyncMock

import pytest

from crabagent.serve.api import chatgpt_auth, provider


@pytest.mark.asyncio
async def test_codex_metadata_reaches_provider_models(monkeypatch):
    cache = {"slug": None, "slugs": None, "context": {}, "efforts": {}, "fetched_at": 0.0}
    monkeypatch.setattr(chatgpt_auth, "_codex_model_cache", cache)
    monkeypatch.setattr(chatgpt_auth, "get_chatgpt_access_token", AsyncMock(return_value="token"))
    monkeypatch.setattr(chatgpt_auth, "_register_dynamic_model_cost", lambda *args: None)

    class Response:
        status_code = 200

        def json(self):
            return {"models": [{"slug": "model-a", "supported_reasoning_levels": [
                {"effort": "low"}, {"effort": "xhigh"}, {"bad": "ignored"}
            ]}, {"slug": "model-b", "supported_reasoning_levels": []}]}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(chatgpt_auth.httpx, "AsyncClient", Client)
    await chatgpt_auth._fetch_codex_models()
    assert cache["efforts"] == {"model-a": ["low", "xhigh"], "model-b": []}
    from types import SimpleNamespace
    monkeypatch.setattr(provider, "get_provider", AsyncMock(return_value=SimpleNamespace(provider_type="chatgpt", extra={})))
    result = await provider.get_provider_models("codex", user=None)
    assert result[0]["reasoning_efforts"] == ["low", "xhigh"]
    assert result[1]["reasoning_efforts"] == []

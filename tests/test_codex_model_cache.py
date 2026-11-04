"""Regression tests for the /codex/models cache.

Background: ``gpt-6.1-terra`` only ever came from the live list. A single failed
fetch (e.g. at startup, before the proxy is up) used to lock the *static* list
in for the full 600 s TTL, and the frontend never re-fetched — so the model
silently vanished from the dropdown for the whole app session.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import pytest

from crabagent.core.provider_store import CHATGPT_MODELS
from crabagent.serve.api import chatgpt_auth as ca


def _reset_cache() -> None:
    ca._codex_model_cache.update(
        {"slug": None, "slugs": None, "context": {}, "efforts": {}, "fetched_at": 0.0}
    )


@pytest.fixture(autouse=True)
def _clean_cache():
    _reset_cache()
    yield
    _reset_cache()


def test_static_fallback_mirrors_live_visible_models():
    # gpt-6.1-terra is served by /codex/models at priority 3; the fallback list
    # must contain every visible slug or a network blip hides it.
    assert "gpt-6.1-terra" in CHATGPT_MODELS
    assert CHATGPT_MODELS.index("gpt-6.1-terra") < CHATGPT_MODELS.index("gpt-6-sol")


class _FakeResponse:
    status_code = 200

    def __init__(self, models: list[dict[str, Any]]) -> None:
        self._models = models

    def json(self) -> dict[str, Any]:
        return {"models": self._models}


class _FakeClient:
    def __init__(self, models: list[dict[str, Any]]) -> None:
        self._models = models

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *args, **kwargs):
        return _FakeResponse(self._models)


def _patch_client(monkeypatch, models: list[dict[str, Any]]) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _FakeClient(models))

    async def _token() -> str:
        return "fake-token"

    monkeypatch.setattr(ca, "get_chatgpt_access_token", _token)


def test_hidden_models_are_filtered_out(monkeypatch):
    # The API spells hidden models "hide" — comparing to "hidden" let internal
    # models leak into the selectable dropdown.
    _patch_client(
        monkeypatch,
        [
            {"slug": "gpt-6.1-sol", "visibility": "list", "priority": 1, "max_context_window": 872_000},
            {"slug": "gpt-6.1-terra", "visibility": "list", "priority": 3, "max_context_window": 872_000},
            {"slug": "codex-auto-review", "visibility": "hide", "priority": 43},
            {"slug": "legacy-hidden", "visibility": "hidden", "priority": 44},
        ],
    )

    slugs = asyncio.run(ca.get_codex_model_slugs())

    assert slugs == ["gpt-6.1-sol", "gpt-6.1-terra"]
    assert ca._codex_model_cache["context"]["gpt-6.1-terra"] == 872_000


def test_failed_fetch_caches_fallback_only_briefly(monkeypatch):
    async def _fail(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(ca, "get_chatgpt_access_token", _fail)

    slugs = asyncio.run(ca.get_codex_model_slugs())

    assert "gpt-6.1-terra" in slugs  # fallback still usable
    age = time.monotonic() - ca._codex_model_cache["fetched_at"]
    # Treated as almost-expired, so the live list is retried within a minute
    # instead of being locked out for the whole TTL.
    assert age >= ca._CODEX_MODEL_TTL - ca._CODEX_FALLBACK_RETRY - 5
    assert ca._CODEX_FALLBACK_RETRY < ca._CODEX_MODEL_TTL

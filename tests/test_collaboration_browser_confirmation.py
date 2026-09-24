from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from crabagent.core.agent.tools import collaboration_browser as browser


@pytest.mark.asyncio
async def test_high_risk_click_requires_specific_approval(monkeypatch):
    calls = []

    def bridge(command, payload=None, **kwargs):
        calls.append((command, payload))
        if command == "click":
            return {
                "confirmation_required": True,
                "pending_action_id": "opaque",
                "label": "Delete",
                "url": "https://example.test",
                "page_version": 2,
            }
        return {"clicked": 1, "page_version": 2}

    monkeypatch.setattr(browser, "_bridge_request", bridge)
    confirmations = []

    async def confirm(name, args):
        confirmations.append((name, args))
        return True

    context = SimpleNamespace(
        metadata={"_collab_browser_page_version": 2, "_collab_browser_observation_id": "obs"}, confirm_callback=confirm
    )
    result = json.loads(await browser.collab_browser_click(1, context=context))
    assert result["clicked"] == 1
    assert confirmations == [
        (
            "collab_browser_click",
            {
                "action": "click",
                "label": "Delete",
                "url": "https://example.test",
            },
        )
    ]
    assert [name for name, _ in calls] == ["click", "commit_click"]
    assert calls[1][1]["pending_action_id"] == "opaque"


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm", [None, False])
async def test_high_risk_click_without_approval_never_commits(monkeypatch, confirm):
    calls = []

    def bridge(command, payload=None, **kwargs):
        calls.append(command)
        return {"confirmation_required": True, "pending_action_id": "opaque", "page_version": 3}

    async def deny(_name, _args):
        return False

    monkeypatch.setattr(browser, "_bridge_request", bridge)
    context = SimpleNamespace(
        metadata={"_collab_browser_page_version": 3, "_collab_browser_observation_id": "obs"},
        confirm_callback=deny if confirm is False else None,
    )
    result = json.loads(await browser.collab_browser_click(1, context=context))
    assert result["status"] == "denied"
    assert calls == ["click"]

@pytest.mark.asyncio
async def test_explicit_old_page_version_cannot_override_latest_observation(monkeypatch):
    calls = []
    monkeypatch.setattr(browser, "_bridge_request", lambda command, payload=None, **kwargs: calls.append(command))
    context = SimpleNamespace(metadata={"_collab_browser_page_version": 3, "_collab_browser_observation_id": "new"})
    with pytest.raises(RuntimeError, match="STALE_PAGE"):
        await browser.collab_browser_type(1, "hello", page_version=2, context=context)
    assert not calls

@pytest.mark.asyncio
async def test_mutation_requires_new_observation_even_when_bridge_returns_page_version(monkeypatch):
    calls = []

    def bridge(command, payload=None, **kwargs):
        calls.append(command)
        return {"page_version": 3, "typed": 1}

    monkeypatch.setattr(browser, "_bridge_request", bridge)
    context = SimpleNamespace(metadata={"_collab_browser_page_version": 3, "_collab_browser_observation_id": "obs"})
    await browser.collab_browser_type(1, "hello", context=context)
    with pytest.raises(RuntimeError, match="STALE_PAGE"):
        await browser.collab_browser_type(1, "again", context=context)
    assert calls == ["type"]

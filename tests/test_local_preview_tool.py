import json
from types import SimpleNamespace

import pytest

from crabagent.core.agent.tools import collaboration_browser as browser


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["authorized", "blocked"])
async def test_local_preview_permission_is_owned_by_electron(monkeypatch, status):
    calls = []

    def request(command, payload, *, context):
        calls.append((command, payload))
        return {"status": status, "origin": "http://127.0.0.1:8766"}

    async def audit(*args, **kwargs):
        pass

    monkeypatch.setattr(browser, "_bridge_request", request)
    monkeypatch.setattr(browser, "record_browser_event", audit)
    ctx = SimpleNamespace(metadata={})
    result = json.loads(await browser.collab_browser_authorize_local_preview("http://127.0.0.1:8766/a", ctx))
    assert result["status"] == status
    assert calls == [("authorize_local_preview", {"url": "http://127.0.0.1:8766/a"})]

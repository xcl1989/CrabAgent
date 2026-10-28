from pathlib import Path

import pytest

import crabagent.core.agent.loop as loop
import crabagent.core.agent.tools.collaboration_browser as browser
from crabagent.core.agent.context import AgentContext


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_browser_binding_released_after_run(monkeypatch, failed):
    context = AgentContext(workspace=Path("."))
    calls = []

    async def run(ctx, query):
        ctx.metadata["_collab_browser_used"] = True
        if failed:
            raise RuntimeError("run failed")
        return [query]

    def request(command, payload=None, *, context=None):
        calls.append((command, context))
        return {"released": True}

    monkeypatch.setattr(loop, "_run_agent", run)
    monkeypatch.setattr(browser, "_bridge_request", request)
    if failed:
        with pytest.raises(RuntimeError, match="run failed"):
            await loop.run_agent(context, "test")
    else:
        assert await loop.run_agent(context, "test") == ["test"]
    assert calls == [("release", context)]
    assert "_collab_browser_used" not in context.metadata

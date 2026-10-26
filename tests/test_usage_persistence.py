from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from crabagent.core.agent.context import AgentContext
from crabagent.core.event import AgentEvent, EventType
from crabagent.serve.services.usage import UsagePersistenceListener


@pytest.mark.asyncio
async def test_usage_flush_retries_without_duplicates(monkeypatch):
    context = AgentContext(workspace=Path.cwd(), model="test-model")
    context.metadata.update(resolved_model="actual-model", resolved_provider="provider")
    context.usage_records.append({"prompt_tokens": 10, "completion_tokens": 3})
    save = AsyncMock(side_effect=[RuntimeError("busy"), None, None])
    monkeypatch.setattr("crabagent.serve.services.usage.token_usage_batch_create", save)
    listener = UsagePersistenceListener(context, 7, "wechat-session")
    await listener.on_event(AgentEvent(type=EventType.ITERATION_END))
    assert listener.cursor == 0
    await listener.flush()
    await listener.flush()
    assert save.await_count == 2
    assert listener.cursor == 1
    row = save.call_args.args[0][0]
    assert row["user_id"] == 7
    assert row["model"] == "actual-model"
    assert row["provider"] == "provider"
    context.usage_records.append({"completion_tokens": 2})
    await listener.on_event(AgentEvent(type=EventType.SUB_AGENT_END))
    assert len(save.call_args.args[0]) == 1
    assert listener.cursor == 2

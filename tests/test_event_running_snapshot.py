import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from crabagent.serve.api import event as event_api
from crabagent.serve.api import prompt as prompt_api


@pytest.mark.asyncio
@pytest.mark.parametrize("done", [False, True, None])
async def test_connection_snapshot_reports_running_without_waiting_for_output(monkeypatch, done):
    monkeypatch.setattr(event_api, "_verify_sse_token", AsyncMock(return_value=SimpleNamespace(id=1)))
    tasks = {} if done is None else {"session": SimpleNamespace(done=lambda: done)}
    monkeypatch.setattr(prompt_api, "_tasks", tasks)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(event_queues={})))
    response = await event_api.event_stream(request, session_id="session", token="test")
    iterator = response.body_iterator
    first = await anext(iterator)
    payload = json.loads(first.removeprefix("data: ").strip())
    assert payload["data"]["connected"] is True
    assert payload["data"]["running"] is (done is False)
    await iterator.aclose()

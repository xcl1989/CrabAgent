import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from crabagent.core import memory_consolidation_tasks as jobs
from crabagent.serve.api.memory import router
from crabagent.serve.deps import get_current_user


@pytest.mark.asyncio
async def test_background_status_dedup_and_user_isolation(monkeypatch):
    jobs._tasks.clear()
    jobs._workers.clear()
    gate = asyncio.Event()
    calls = []

    async def consolidate(user_id, *, progress):
        calls.append(user_id)
        progress({"stage": "embedding", "completed": 1, "total": 2})
        await gate.wait()
        return {"status": "ok", "merged": user_id}

    monkeypatch.setattr(jobs, "semantic_consolidate", consolidate)
    app = FastAPI()
    app.include_router(router)
    current = SimpleNamespace(id=1)
    app.dependency_overrides[get_current_user] = lambda: current
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get('/memory/semantic-consolidate/status')).json()['status'] == 'idle'
        first = (await client.post('/memory/semantic-consolidate')).json()
        duplicate = (await client.post('/memory/semantic-consolidate')).json()
        assert first['task_id'] == duplicate['task_id']
        await asyncio.sleep(0)
        running = (await client.get('/memory/semantic-consolidate/status')).json()
        assert running['progress']['completed'] == 1
        current.id = 2
        assert (await client.get('/memory/semantic-consolidate/status')).json()['status'] == 'idle'
        other = (await client.post('/memory/semantic-consolidate')).json()
        assert other['task_id'] != first['task_id']
        await asyncio.sleep(0)
        gate.set()
        await asyncio.gather(*list(jobs._workers.values()))
        assert (await client.get('/memory/semantic-consolidate/status')).json()['result']['merged'] == 2
        current.id = 1
        assert (await client.get('/memory/semantic-consolidate/status')).json()['result']['merged'] == 1
        assert calls == [1, 2]
        assert (await client.post('/memory/semantic-consolidate')).json()['task_id'] != first['task_id']
        await jobs._workers[1]


@pytest.mark.asyncio
async def test_background_failure_and_retry(monkeypatch):
    jobs._tasks.clear()
    jobs._workers.clear()

    async def fail(user_id, *, progress):
        raise ValueError('private details')

    monkeypatch.setattr(jobs, 'semantic_consolidate', fail)
    first = jobs.start(1)
    await jobs._workers[1]
    failed = jobs.status(1)
    assert failed['status'] == 'failed'
    assert failed['result']['reason'] == 'internal_error'
    assert failed['finished_at']
    assert jobs.start(1)['task_id'] != first['task_id']
    await jobs._workers[1]

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from crabagent.core.agent.agents import BackgroundAgentResult
from crabagent.core.agent.tools.agent import run_pipeline


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setattr('crabagent.core.database.run_record_create', AsyncMock(return_value=1))
    return SimpleNamespace(metadata={}, event_bus=SimpleNamespace(emit=AsyncMock()))


def step(id, deps=()):
    return {'id': id, 'agent_name': 'agent', 'task': id, 'depends_on': list(deps)}


@pytest.mark.asyncio
@pytest.mark.parametrize('steps, error', [
    ([step('a'), step('a')], 'duplicate'),
    ([step('a', ['missing'])], 'unknown'),
    ([step('a', ['a'])], 'cyclic'),
    ([step('a', ['b']), step('b', ['a'])], 'cyclic'),
])
async def test_invalid_graph_has_no_side_effects(context, monkeypatch, steps, error):
    spawn = AsyncMock()
    monkeypatch.setattr('crabagent.core.agent.agents.spawn_sub_agent', spawn)
    assert error in await run_pipeline(steps, context)
    spawn.assert_not_called()
    context.event_bus.emit.assert_not_called()


@pytest.mark.asyncio
async def test_dynamic_scheduling_and_failure_propagation(context, monkeypatch):
    slow_started = asyncio.Event()
    child_started = asyncio.Event()
    async def spawn(agent, task, ctx, **kwargs):
        sid = kwargs['pipeline_step_id']
        if sid == 'slow':
            slow_started.set()
            await asyncio.wait_for(child_started.wait(), 1)
        if sid == 'fast':
            await slow_started.wait()
            return BackgroundAgentResult('succeeded', 'Error: valid answer')
        if sid == 'child':
            assert 'Error: valid answer' in task
            child_started.set()
        if sid == 'bad':
            return BackgroundAgentResult('failed', 'failure without error prefix')
        assert sid not in ('blocked', 'transitive')
        return BackgroundAgentResult('succeeded', 'ok')
    monkeypatch.setattr('crabagent.core.agent.agents.spawn_sub_agent', spawn)
    result = await run_pipeline([step('slow'), step('fast'), step('child', ['fast']),
                                 step('bad'), step('blocked', ['bad']),
                                 step('transitive', ['blocked'])], context)
    assert '(3/6 succeeded)' in result
    assert 'Step: child [OK]' in result
    assert 'Step: transitive [FAIL]' in result


@pytest.mark.asyncio
async def test_cancellation_cleans_up_children(context, monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()
    async def spawn(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    monkeypatch.setattr('crabagent.core.agent.agents.spawn_sub_agent', spawn)
    task = asyncio.create_task(run_pipeline([step('a')], context))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()

import asyncio
import subprocess
import sys

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core import database as db
from crabagent.core.agent import agents, background, background_group
from tests.test_background_delegation import context, session_factory  # noqa: F401


@pytest.fixture(autouse=True)
async def cleanup_groups():
    yield
    for job in list(background_group._groups.values()):
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)


async def test_dynamic_dependencies_and_failure(session_factory, monkeypatch):
    gate = asyncio.Event()
    started = asyncio.Event()
    async def agent(_):
        return {"name": "a"}
    async def spawn(name, task, ctx, **kwargs):
        assert kwargs["background"] and not ctx.tool_registry._tools
        if task == "slow":
            await gate.wait()
        if task.startswith("downstream"):
            assert '"fast": "fast result"' in task
            started.set()
        return agents.BackgroundAgentResult("failed" if task == "bad" else "succeeded", task + " result")
    monkeypatch.setattr(agents, "get_agent", agent)
    monkeypatch.setattr(agents, "spawn_sub_agent", spawn)
    steps = [{"id": sid, "agent_name": "a", "task": task, "depends_on": deps} for sid, task, deps in [
        ("fast", "fast", []), ("slow", "slow", []), ("next", "downstream", ["fast"]),
        ("bad", "bad", []), ("blocked", "blocked", ["bad"])]]
    gid = await background_group.start(context(), steps)
    await asyncio.wait_for(started.wait(), 3)
    assert (await background_group.get(context(), gid))["status"] == "running"
    gate.set()
    result = await background_group.wait(context(), gid, 3)
    assert result["status"] == "failed"
    states = {s["step_id"]: s["status"] for s in result["steps"]}
    assert states == {"fast": "succeeded", "slow": "succeeded", "next": "succeeded", "bad": "failed", "blocked": "skipped"}
    with pytest.raises(ValueError):
        await background_group.get(context(user=2), gid)
    async with session_factory() as conn:
        assert await conn.scalar(select(db.BackgroundGroup).where(db.BackgroundGroup.id == gid))


async def test_validation_and_cancel(session_factory, monkeypatch):
    async def agent(_): return {"name": "a"}
    async def spawn(*args, **kwargs): await asyncio.sleep(10)
    monkeypatch.setattr(agents, "get_agent", agent)
    monkeypatch.setattr(agents, "spawn_sub_agent", spawn)
    step = {"id": "a", "agent_name": "a", "task": "task"}
    for steps in ([step, step], [dict(step, depends_on=["missing"])], [dict(step, depends_on=["a"])], [dict(step, allowed_tools=["write"]) ]):
        with pytest.raises(ValueError):
            await background_group.start(context(), steps)
    gid = await background_group.start(context(), [step])
    result = await background_group.cancel(context(), gid)
    assert result["status"] == "cancelled"
    assert result["steps"][0]["status"] == "cancelled"
    gid = await background_group.start(context(), [step])
    for _ in range(100):
        row = await background_group.get(context(), gid)
        if row["steps"][0]["status"] == "running": break
        await asyncio.sleep(.01)
    result = await background_group.cancel(context(), gid)
    assert result["steps"][0]["status"] == "cancelled"
    assert (await background.get(context(), result["steps"][0]["job_id"]))["status"] == "cancelled"


async def test_cancel_during_start(session_factory, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    original = background.start
    async def agent(_): return {"name": "a"}
    async def spawn(*args, **kwargs): await asyncio.sleep(10)
    async def delayed(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)
    monkeypatch.setattr(agents, "get_agent", agent)
    monkeypatch.setattr(agents, "spawn_sub_agent", spawn)
    monkeypatch.setattr(background, "start", delayed)
    gid = await background_group.start(context(), [{"id": "a", "agent_name": "a", "task": "task"}])
    await asyncio.wait_for(entered.wait(), 2)
    cancelling = asyncio.create_task(background_group.cancel(context(), gid))
    await asyncio.sleep(.05)
    release.set()
    assert (await cancelling)["status"] == "cancelled"
    async with session_factory() as conn:
        jobs = (await conn.scalars(select(db.BackgroundDelegation))).all()
        assert not jobs  # The group cancellation won the transactional start race.


async def test_recovery_and_tools(session_factory, monkeypatch):
    from crabagent.core.agent.tools.agent import background_group_start, background_group_status
    async def agent(_): return {"name": "a"}
    monkeypatch.setattr(agents, "get_agent", agent)
    async with session_factory() as conn:
        conn.add(db.BackgroundGroup(id="old", user_id=1, session_id="session", branch_id="main", status="running"))
        conn.add(db.BackgroundGroupStep(group_id="old", step_id="a", agent_name="a", task="x", depends_on=[], allowed_tools=[], status="running", result="", job_id=""))
        await conn.commit()
    await background._ensure_executor()
    result = await background_group.get(context(), "old")
    assert result["status"] == "interrupted" and result["steps"][0]["status"] == "interrupted"
    assert '"interrupted"' in await background_group_status("old", context=context())
    assert (await background_group_start([], context=context())).startswith("Error:")

async def test_opt_in_summary_concurrency_and_failure(session_factory, monkeypatch):
    import json
    async def agent(_): return {"name": "a"}
    async def spawn(name, task, ctx, **kwargs):
        assert not ctx.tool_registry._tools
        await asyncio.sleep(.01)
        return agents.BackgroundAgentResult("failed" if task == "bad" else "succeeded", task)
    monkeypatch.setattr(agents, "get_agent", agent)
    monkeypatch.setattr(agents, "spawn_sub_agent", spawn)
    steps = [{"id": "a", "agent_name": "a", "task": "bad"}]
    ids = await asyncio.gather(*(background_group.start(context(), steps, auto_summary=True) for _ in range(2)))
    rows = await asyncio.gather(*(background_group.wait(context(), gid, 5) for gid in ids))
    for row in rows:
        assert row["status"] == "failed"
        assert row["summary"]["status"] == "succeeded"
        assert json.loads(row["summary"]["text"])["steps"][0]["result"] == "bad"
    gid = await background_group.start(context(), steps)
    assert (await background_group.wait(context(), gid, 5))["summary"] is None


async def test_opt_in_summary_cancel_and_recovery(session_factory, monkeypatch):
    async def agent(_): return {"name": "a"}
    async def spawn(*args, **kwargs): await asyncio.sleep(10)
    monkeypatch.setattr(agents, "get_agent", agent)
    monkeypatch.setattr(agents, "spawn_sub_agent", spawn)
    gid = await background_group.start(context(), [{"id": "a", "agent_name": "a", "task": "x"}], auto_summary=True)
    row = await background_group.cancel(context(), gid)
    assert row["summary"] == {"status": "cancelled", "text": ""}
    async with session_factory() as conn:
        conn.add(db.BackgroundGroup(id="orphan", user_id=1, session_id="s", branch_id="b", status="running"))
        conn.add(db.BackgroundGroupSummary(group_id="orphan", status="pending", text=""))
        await conn.commit()
    await background._interrupt_orphans()
    async with session_factory() as conn:
        assert (await conn.get(db.BackgroundGroupSummary, "orphan")).status == "interrupted"


async def test_branch_switch_does_not_stop_scheduler(session_factory, monkeypatch):
    gate, entered = asyncio.Event(), asyncio.Event()
    async def agent(_): return {"name": "a"}
    async def spawn(name, task, ctx, **kwargs):
        if task == "first":
            entered.set()
            await gate.wait()
        return agents.BackgroundAgentResult("succeeded", task)
    monkeypatch.setattr(agents, "get_agent", agent)
    monkeypatch.setattr(agents, "spawn_sub_agent", spawn)
    gid = await background_group.start(context(), [
        {"id": "a", "agent_name": "a", "task": "first"},
        {"id": "b", "agent_name": "a", "task": "second", "depends_on": ["a"]}])
    await asyncio.wait_for(entered.wait(), 2)
    async with session_factory() as conn:
        conversation = await conn.scalar(select(db.Conversation))
        conversation.active_branch = "other"
        await conn.commit()
    gate.set()
    await asyncio.wait_for(asyncio.shield(background_group._groups[gid]), 3)
    with pytest.raises(ValueError):
        await background_group.get(context(), gid)
    async with session_factory() as conn:
        assert (await conn.get(db.BackgroundGroup, gid)).status == "succeeded"


async def test_concurrent_cancel_waits_for_cleanup(session_factory, monkeypatch):
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def agent(_): return {"name": "a"}
    async def spawn(*args, **kwargs):
        entered.set()
        try:
            await asyncio.sleep(10)
        finally:
            cleaning.set()
            await release.wait()
    monkeypatch.setattr(agents, "get_agent", agent)
    monkeypatch.setattr(agents, "spawn_sub_agent", spawn)
    gid = await background_group.start(context(), [{"id": "a", "agent_name": "a", "task": "x"}], auto_summary=True)
    await asyncio.wait_for(entered.wait(), 2)
    first = asyncio.create_task(background_group.cancel(context(), gid))
    await asyncio.wait_for(cleaning.wait(), 2)
    second = asyncio.create_task(background_group.cancel(context(), gid))
    await asyncio.sleep(.05)
    assert (await background_group.get(context(), gid))["status"] == "cancelling"
    assert not first.done() and not second.done()
    release.set()
    rows = await asyncio.gather(first, second)
    assert all(row["status"] == "cancelled" and row["summary"]["status"] == "cancelled" for row in rows)


async def test_read_recovers_cancelling_group(session_factory):
    async with session_factory() as conn:
        conn.add(db.BackgroundGroup(id="old", user_id=1, session_id="session", branch_id="main", status="cancelling"))
        conn.add(db.BackgroundGroupStep(group_id="old", step_id="a", agent_name="a", task="x", depends_on=[], allowed_tools=[], status="running", result="", job_id="job"))
        conn.add(db.BackgroundGroupSummary(group_id="old", status="pending", text=""))
        conn.add(db.BackgroundDelegation(id="job", user_id=1, session_id="session", branch_id="main", agent_name="a", task="x", status="running", result=""))
        await conn.commit()
    row = await background_group.get(context(), "old")
    assert row["status"] == row["steps"][0]["status"] == row["summary"]["status"] == "interrupted"
    assert (await background.get(context(), "job"))["status"] == "interrupted"


async def test_other_process_lock_does_not_recover(session_factory, monkeypatch):
    import fcntl
    import os
    path = os.path.realpath(session_factory.kw["bind"].url.database) + ".background.lock"
    with open(path, "a") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        async with session_factory() as conn:
            conn.add(db.BackgroundGroup(id="remote", user_id=1, session_id="session", branch_id="main", status="running"))
            await conn.commit()
        assert (await background_group.get(context(), "remote"))["status"] == "running"
        assert (await background_group.cancel(context(), "remote"))["status"] == "cancelling"


async def test_job_and_step_link_before_execution(session_factory, monkeypatch):
    checked = asyncio.Event()
    async def agent(_): return {"name": "a"}
    async def spawn(name, task, ctx, **kwargs):
        async with session_factory() as conn:
            step = await conn.scalar(select(db.BackgroundGroupStep))
            assert step.job_id
            assert await conn.get(db.BackgroundDelegation, step.job_id)
        checked.set()
        return agents.BackgroundAgentResult("succeeded", "ok")
    monkeypatch.setattr(agents, "get_agent", agent)
    monkeypatch.setattr(agents, "spawn_sub_agent", spawn)
    gid = await background_group.start(context(), [{"id": "a", "agent_name": "a", "task": "x"}])
    await asyncio.wait_for(checked.wait(), 2)
    assert (await background_group.wait(context(), gid, 2))["status"] == "succeeded"


async def test_single_cancel_waits_for_cleanup_before_group_completion(session_factory, monkeypatch):
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def agent(_): return {"name": "a"}
    async def spawn(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
    monkeypatch.setattr(agents, "get_agent", agent)
    monkeypatch.setattr(agents, "spawn_sub_agent", spawn)
    gid = await background_group.start(context(), [{"id": "a", "agent_name": "a", "task": "x"}], auto_summary=True)
    await asyncio.wait_for(entered.wait(), 3)
    jid = (await background_group.get(context(), gid))["steps"][0]["job_id"]
    first = asyncio.create_task(background.cancel(context(), jid))
    await asyncio.wait_for(cleaning.wait(), 3)
    second = asyncio.create_task(background.cancel(context(), jid))
    try:
        await asyncio.sleep(.3)
        assert (await background.get(context(), jid))["status"] == "cancelling"
        group = await background_group.get(context(), gid)
        assert group["status"] == "running"
        assert group["summary"]["status"] == "pending"
        assert not first.done() and not second.done()
    finally:
        release.set()
    assert (await first)["status"] == "cancelled"
    assert (await second)["status"] == "cancelled"
    group = await background_group.wait(context(), gid, 3)
    assert group["status"] == "failed"
    assert group["steps"][0]["status"] == "cancelled"


async def test_group_input_limits_use_utf8_bytes(session_factory, monkeypatch):
    monkeypatch.setattr(background_group, "MAX_STEP_INPUT_BYTES", 6)
    monkeypatch.setattr(background_group, "MAX_GROUP_INPUT_BYTES", 1000)
    step = {"id": "a", "agent_name": "a", "task": "中文"}
    background_group._validate([step])
    with pytest.raises(ValueError, match="step input bytes"):
        background_group._validate([dict(step, task="中文x")])
    monkeypatch.setattr(background_group, "MAX_GROUP_INPUT_BYTES", 10)
    with pytest.raises(ValueError, match="group input bytes"):
        background_group._validate([step])


async def test_dependency_budget_fails_step_and_skips_descendant(session_factory, monkeypatch):
    async def agent(_): return {"name": "a"}
    async def spawn(name, task, ctx, **kwargs):
        assert task == "first"
        return agents.BackgroundAgentResult("succeeded", "中文中文")
    monkeypatch.setattr(agents, "get_agent", agent)
    monkeypatch.setattr(agents, "spawn_sub_agent", spawn)
    monkeypatch.setattr(background_group, "MAX_DEPENDENCY_BYTES", 12)
    gid = await background_group.start(context(), [
        {"id": "a", "agent_name": "a", "task": "first"},
        {"id": "b", "agent_name": "a", "task": "second", "depends_on": ["a"]},
        {"id": "c", "agent_name": "a", "task": "third", "depends_on": ["b"]},
    ], auto_summary=True)
    row = await background_group.wait(context(), gid, 3)
    steps = {s["step_id"]: s for s in row["steps"]}
    assert row["status"] == "failed" and row["summary"]["status"] == "succeeded"
    assert steps["b"]["status"] == "failed" and "Resource limit exceeded" in steps["b"]["result"]
    assert steps["b"]["job_id"] == "" and steps["c"]["status"] == "skipped"


async def test_group_and_step_concurrency_limits(session_factory, monkeypatch):
    gate, entered = asyncio.Event(), asyncio.Event()
    active = 0
    maximum = 0
    async def agent(_): return {"name": "a"}
    async def spawn(name, task, ctx, **kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        if active == 2:
            entered.set()
        try:
            await gate.wait()
            return agents.BackgroundAgentResult("succeeded", "ok")
        finally:
            active -= 1
    monkeypatch.setattr(agents, "get_agent", agent)
    monkeypatch.setattr(agents, "spawn_sub_agent", spawn)
    monkeypatch.setattr(background_group, "MAX_ACTIVE_GROUPS", 1)
    monkeypatch.setattr(background_group, "MAX_PARALLEL_STEPS", 2)
    steps = [{"id": str(i), "agent_name": "a", "task": "x"} for i in range(5)]
    gid = await background_group.start(context(), steps)
    await asyncio.wait_for(entered.wait(), 3)
    with pytest.raises(ValueError, match="active group capacity"):
        await background_group.start(context(), steps)
    await asyncio.sleep(.15)
    assert maximum == 2
    gate.set()
    assert (await background_group.wait(context(), gid, 3))["status"] == "succeeded"


async def test_cross_process_group_cancel_waits_for_cleanup(session_factory, tmp_path, monkeypatch):
    import sys

    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def agent(_): return {"name": "a"}
    async def spawn(*args, **kwargs):
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
    monkeypatch.setattr(agents, "get_agent", agent)
    monkeypatch.setattr(agents, "spawn_sub_agent", spawn)
    gid = await background_group.start(context(), [
        {"id": "a", "agent_name": "a", "task": "task"},
        {"id": "b", "agent_name": "a", "task": "later", "depends_on": ["a"]},
    ], auto_summary=True)
    await asyncio.wait_for(entered.wait(), 3)
    script = '''
import asyncio, sys
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from crabagent.core import database as db
from crabagent.core.agent import background_group
from crabagent.core.agent.context import AgentContext
async def main():
    engine = create_async_engine("sqlite+aiosqlite:///" + sys.argv[1])
    db.async_session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ctx = AgentContext(workspace=Path("."))
    ctx.metadata.update(user_id=1, session_id="session", branch_id="main")
    print((await background_group.cancel(ctx, sys.argv[2]))["status"], flush=True)
    await engine.dispose()
asyncio.run(main())
'''
    proc = await asyncio.create_subprocess_exec(sys.executable, "-c", script,
        str(tmp_path / "test.db"), gid, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await asyncio.wait_for(proc.communicate(), 15)
    assert proc.returncode == 0, stderr.decode()
    assert stdout.decode().strip() == "cancelling"
    await asyncio.wait_for(cleaning.wait(), 3)
    row = await background_group.get(context(), gid)
    assert row["status"] == "cancelling"
    assert row["summary"]["status"] == "pending"
    release.set()
    row = await background_group.wait(context(), gid, 3)
    assert row["status"] == "cancelled"
    assert row["summary"]["status"] == "cancelled"
    assert all(step["status"] == "cancelled" for step in row["steps"])
    assert (await background.get(context(), row["steps"][0]["job_id"]))["status"] == "cancelled"


async def test_forwarded_group_start_executed_by_owner_process(session_factory, tmp_path, monkeypatch):
    """A non-owner process forwards group starts to the owning executor."""
    database = tmp_path / "group-forward.db"
    owner_ready = tmp_path / "owner.ready"

    code = '''
import asyncio, sys
from pathlib import Path
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from crabagent.core import database as db
from crabagent.core.agent import agents, background


async def agent(_):
    return {"name": "a"}


async def spawn(name, task, ctx, **kwargs):
    return agents.BackgroundAgentResult("succeeded", task + " ok")


async def main():
    agents.get_agent = agent
    agents.spawn_sub_agent = spawn
    engine = create_async_engine("sqlite+aiosqlite:///" + sys.argv[1])
    async with engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    db.async_session_factory = async_sessionmaker(engine, expire_on_commit=False)
    background._claim_executor()
    await background._ensure_executor()
    Path(sys.argv[2]).write_text("ready")
    await asyncio.sleep(30)


asyncio.run(main())
'''
    proc = subprocess.Popen([sys.executable, "-c", code, str(database), str(owner_ready)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(100):
            if owner_ready.exists():
                break
            await asyncio.sleep(0.05)
        assert owner_ready.exists(), "owner process did not start"

        engine2 = create_async_engine(f"sqlite+aiosqlite:///{database}")
        factory2 = async_sessionmaker(engine2, expire_on_commit=False)
        monkeypatch.setattr(db, "async_session_factory", factory2)
        async with factory2() as session:
            session.add(db.Conversation(session_id="session", user_id=1, active_branch="main"))
            await session.commit()

        async def local_agent(_):
            return {"name": "a"}
        monkeypatch.setattr(agents, "get_agent", local_agent)

        ctx = context()
        steps = [{"id": "one", "agent_name": "a", "task": "forwarded"},
                 {"id": "two", "agent_name": "a", "task": "after", "depends_on": ["one"]}]
        gid = await background_group.start(ctx, steps)
        result = await background_group.wait(ctx, gid, 15)
        assert result["status"] == "succeeded", result
        states = {s["step_id"]: s["status"] for s in result["steps"]}
        assert states == {"one": "succeeded", "two": "succeeded"}
        async with factory2() as conn:
            commands = (await conn.scalars(select(db.BackgroundStartCommand))).all()
        assert [c.status for c in commands] == ["done"]
        await engine2.dispose()
    finally:
        proc.kill()
        await asyncio.get_running_loop().run_in_executor(None, proc.wait)

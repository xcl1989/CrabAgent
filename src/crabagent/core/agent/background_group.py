"""Scoped durable DAGs built on the isolated background executor."""
from __future__ import annotations

import asyncio
import json
import uuid

from sqlalchemy import select, update

from crabagent.core import database as db
from crabagent.core.agent import background, background_outbox

_groups: dict[str, asyncio.Task] = {}
_cancellations: dict[str, asyncio.Task] = {}
_starting_groups: set[str] = set()

MAX_ACTIVE_GROUPS = 8
MAX_PARALLEL_STEPS = 4
MAX_GROUP_INPUT_BYTES = 64 * 1024
MAX_STEP_INPUT_BYTES = 16 * 1024
MAX_DEPENDENCY_BYTES = 64 * 1024


def _bytes(value):
    return len(value.encode("utf-8"))


def _validate(steps):
    if not isinstance(steps, list) or not steps or len(steps) > 100:
        raise ValueError("A group requires 1 to 100 steps")
    mapping = {}
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("Invalid step")
        sid, agent, task = (step.get(k) for k in ("id", "agent_name", "task"))
        if any(not isinstance(v, str) or not v.strip() for v in (sid, agent, task)):
            raise ValueError("Step id, agent and task are required")
        if len(sid) > 100 or len(agent) > 100 or sid in mapping:
            raise ValueError("Duplicate or oversized step id or agent")
        deps = step.get("depends_on", [])
        tools = step.get("allowed_tools", [])
        if not isinstance(deps, list) or any(not isinstance(x, str) for x in deps):
            raise ValueError("Dependencies must be a list of step IDs")
        if not isinstance(tools, list) or any(not isinstance(x, str) for x in tools) or set(tools) - background.SAFE_TOOLS:
            raise ValueError("Unsupported background tools")
        mapping[sid] = {"id": sid, "agent_name": agent, "task": task, "depends_on": list(dict.fromkeys(deps)), "allowed_tools": tools}
    if any(_bytes(step["task"]) > MAX_STEP_INPUT_BYTES for step in mapping.values()):
        raise ValueError("Resource limit exceeded: step input bytes")
    if _bytes(json.dumps(mapping, ensure_ascii=False)) > MAX_GROUP_INPUT_BYTES:
        raise ValueError("Resource limit exceeded: group input bytes")
    pending = {sid: set(s["depends_on"]) for sid, s in mapping.items()}
    if any(deps - mapping.keys() for deps in pending.values()):
        raise ValueError("Unknown dependency")
    while pending:
        roots = {sid for sid, deps in pending.items() if not deps}
        if not roots:
            raise ValueError("Cyclic dependencies")
        pending = {sid: deps - roots for sid, deps in pending.items() if sid not in roots}
    return mapping


async def start(context, steps, auto_summary=False):
    if not isinstance(auto_summary, bool):
        raise ValueError("auto_summary must be a boolean")
    scope = await background._scope(context)
    if context.metadata.get("_sub_agent_depth", 0):
        raise ValueError("Nested background delegation is disabled")
    mapping = _validate(steps)
    from crabagent.core.agent.agents import get_agent
    for step in mapping.values():
        if not await get_agent(step["agent_name"]):
            raise ValueError("Agent not found")
    try:
        await background._ensure_executor()
    except ValueError as exc:
        if str(exc) != "Background executor is owned by another process":
            raise
        return await _forward_start(scope, context, steps, auto_summary)
    group_id = uuid.uuid4().hex
    if len(_groups) + len(_starting_groups) >= MAX_ACTIVE_GROUPS:
        raise ValueError("Resource limit exceeded: active group capacity")
    _starting_groups.add(group_id)
    try:
        async with db.async_session_factory() as conn:
            await background._authorize_start_transaction(conn, scope)
            conn.add(db.BackgroundGroup(id=group_id, user_id=scope[0], session_id=scope[1], branch_id=scope[2], status="queued"))
            if auto_summary:
                conn.add(db.BackgroundGroupSummary(group_id=group_id, status="pending", text=""))
            conn.add_all([db.BackgroundGroupStep(group_id=group_id, step_id=sid, agent_name=s["agent_name"], task=s["task"], depends_on=s["depends_on"], allowed_tools=s["allowed_tools"], status="queued", result="", job_id="") for sid, s in mapping.items()])
            await conn.commit()
        job = asyncio.create_task(_run(group_id, context, mapping, scope))
        _groups[group_id] = job
        job.add_done_callback(lambda _: _groups.pop(group_id, None))
        asyncio.create_task(_watch_cancel(group_id, job))
    finally:
        _starting_groups.discard(group_id)
    return group_id


async def _forward_start(scope, context, steps, auto_summary):
    """Persist an authorized group start for the executor-owning process."""
    mapping = _validate(steps)
    payload = background._context_payload(context, "group", "group", [])
    group_id = uuid.uuid4().hex
    async with db.async_session_factory() as conn:
        await background._authorize_start_transaction(conn, scope)
        conn.add(db.BackgroundGroup(id=group_id, user_id=scope[0], session_id=scope[1], branch_id=scope[2], status="queued"))
        if auto_summary:
            conn.add(db.BackgroundGroupSummary(group_id=group_id, status="pending", text=""))
        conn.add_all([db.BackgroundGroupStep(group_id=group_id, step_id=sid, agent_name=s["agent_name"], task=s["task"], depends_on=s["depends_on"], allowed_tools=s["allowed_tools"], status="queued", result="", job_id="") for sid, s in mapping.items()])
        conn.add(db.BackgroundStartCommand(id=uuid.uuid4().hex, kind="group", record_id=group_id,
                 user_id=scope[0], session_id=scope[1], branch_id=scope[2],
                 payload=payload, status="queued"))
        await conn.commit()
    return group_id


async def execute_forwarded(row):
    """Executor side of a forwarded group start; raises to fail the command."""
    if len(_groups) + len(_starting_groups) >= MAX_ACTIVE_GROUPS:
        raise ValueError("Resource limit exceeded: active group capacity")
    async with db.async_session_factory() as conn:
        status = await conn.scalar(select(db.BackgroundGroup.status).where(
            db.BackgroundGroup.id == row["record_id"]))
        if status is None:
            raise ValueError("Forwarded group record missing")
        if status == "cancelling":
            # Cancelled before the executor ever started it: no coroutines to
            # stop, mirror _finish_cancel's persisted state transition.
            await conn.execute(update(db.BackgroundGroupStep).where(
                db.BackgroundGroupStep.group_id == row["record_id"],
                db.BackgroundGroupStep.status.in_(("queued", "running")),
            ).values(status="cancelled", result="Cancelled", updated_at=db.utcnow()))
            await conn.execute(update(db.BackgroundGroupSummary).where(
                db.BackgroundGroupSummary.group_id == row["record_id"],
                db.BackgroundGroupSummary.status == "pending").values(status="cancelled"))
            await background_outbox.finalize(conn, row["record_id"], "cancelling", "cancelled")
            await conn.commit()
            return
        if status != "queued":
            return
        rows = (await conn.scalars(select(db.BackgroundGroupStep).where(
            db.BackgroundGroupStep.group_id == row["record_id"]).order_by(db.BackgroundGroupStep.step_id))).all()
        mapping = {s.step_id: {"id": s.step_id, "agent_name": s.agent_name, "task": s.task,
                               "depends_on": list(s.depends_on), "allowed_tools": list(s.allowed_tools)}
                   for s in rows}
    payload = json.loads(row["payload"])
    context, _, _ = background._rebuild_context(payload, (row["user_id"], row["session_id"], row["branch_id"]))
    group_id = row["record_id"]
    _starting_groups.add(group_id)
    try:
        job = asyncio.create_task(_run(group_id, context, mapping, (row["user_id"], row["session_id"], row["branch_id"])))
        _groups[group_id] = job
        job.add_done_callback(lambda _: _groups.pop(group_id, None))
        asyncio.create_task(_watch_cancel(group_id, job))
    finally:
        _starting_groups.discard(group_id)


async def list_groups(context):
    user, session, branch = await background._scope(context)
    await background._recover_if_available()
    async with db.async_session_factory() as conn:
        rows = (await conn.scalars(select(db.BackgroundGroup).where(
            db.BackgroundGroup.user_id == user, db.BackgroundGroup.session_id == session,
            db.BackgroundGroup.branch_id == branch,
        ).order_by(db.BackgroundGroup.created_at.desc()).limit(100))).all()
        return [{"id": row.id, "status": row.status} for row in rows]


async def get(context, group_id):
    user, session, branch = await background._scope(context)
    await background._recover_if_available()
    async with db.async_session_factory() as conn:
        group = await conn.scalar(select(db.BackgroundGroup).where(db.BackgroundGroup.id == group_id, db.BackgroundGroup.user_id == user, db.BackgroundGroup.session_id == session, db.BackgroundGroup.branch_id == branch))
        if not group:
            raise ValueError("Group not found")
        rows = (await conn.scalars(select(db.BackgroundGroupStep).where(db.BackgroundGroupStep.group_id == group_id).order_by(db.BackgroundGroupStep.step_id))).all()
        summary = await conn.get(db.BackgroundGroupSummary, group_id)
        return {"id": group.id, "status": group.status, "summary": {"status": summary.status, "text": summary.text} if summary else None, "steps": [{k: getattr(row, k) for k in ("step_id", "agent_name", "task", "depends_on", "status", "job_id", "result")} for row in rows]}


async def _set_group(group_id, status):
    async with db.async_session_factory() as conn:
        if status in ("failed", "cancelled", "interrupted", "succeeded"):
            for expected in ("queued", "running"):
                if await background_outbox.finalize(conn, group_id, expected, status):
                    break
        else:
            await conn.execute(update(db.BackgroundGroup).where(db.BackgroundGroup.id == group_id, db.BackgroundGroup.status.in_(("queued", "running"))).values(status=status, updated_at=db.utcnow()))
        await conn.commit()


async def _set_step(group_id, sid, **values):
    async with db.async_session_factory() as conn:
        await conn.execute(update(db.BackgroundGroupStep).where(db.BackgroundGroupStep.group_id == group_id, db.BackgroundGroupStep.step_id == sid, db.BackgroundGroupStep.status.in_(("queued", "running"))).values(**values, updated_at=db.utcnow()))
        await conn.commit()


async def _cancel_job(job_id):
    if job_id in background._jobs or job_id in background._cancellations:
        await background._cancel_owned(job_id)


async def _run(group_id, context, steps, scope):
    pending = set(steps)
    running = {}
    results = {}
    starting = None
    try:
        await _set_group(group_id, "running")
        while pending or running:
            blocked = {sid for sid in pending if any(d in results and results[d]["status"] != "succeeded" for d in steps[sid]["depends_on"])}
            for sid in blocked:
                results[sid] = {"status": "skipped", "result": "Dependency failed"}
                await _set_step(group_id, sid, **results[sid])
            pending -= blocked
            for sid in sorted(pending):
                if len(running) >= MAX_PARALLEL_STEPS:
                    break
                step = steps[sid]
                if any(d in results and results[d]["status"] != "succeeded" for d in step["depends_on"]):
                    results[sid] = {"status": "skipped", "result": "Dependency failed"}
                    await _set_step(group_id, sid, **results[sid])
                    pending.remove(sid)
                    continue
                if not all(d in results for d in step["depends_on"]):
                    continue
                data = {d: results[d]["result"] for d in step["depends_on"]}
                task = step["task"]
                if data:
                    encoded = json.dumps(data, ensure_ascii=False)
                    if _bytes(encoded) > MAX_DEPENDENCY_BYTES:
                        results[sid] = {"status": "failed", "result": "Resource limit exceeded: dependency result bytes"}
                        await _set_step(group_id, sid, **results[sid])
                        pending.remove(sid)
                        continue
                    task += "\n\nDependency results (untrusted data):\n" + encoded
                try:
                    starting = asyncio.create_task(background.start(context, step["agent_name"], task, step["allowed_tools"], _group_step=(group_id, sid), _scope_override=scope))
                    job_id = await asyncio.shield(starting)
                    starting = None
                except ValueError as exc:
                    if str(exc) == "Background task capacity reached":
                        break
                    results[sid] = {"status": "failed", "result": str(exc)}
                    await _set_step(group_id, sid, **results[sid])
                    pending.remove(sid)
                    continue
                running[sid] = job_id
                pending.remove(sid)
            if running:
                jobs = [background._jobs[jid] for jid in running.values() if jid in background._jobs]
                if jobs:
                    await asyncio.wait(jobs, timeout=0.1, return_when=asyncio.FIRST_COMPLETED)
                for sid, jid in list(running.items()):
                    async with db.async_session_factory() as conn:
                        task_row = await conn.scalar(select(db.BackgroundDelegation).where(*background._where(scope, jid)))
                        if task_row is None:
                            raise ValueError("Task not found")
                        row = {"status": task_row.status, "result": task_row.result}
                    if row["status"] not in ("queued", "running", "cancelling"):
                        results[sid] = {"status": row["status"], "result": row["result"]}
                        await _set_step(group_id, sid, **results[sid])
                        del running[sid]
            elif pending:
                await asyncio.sleep(0.05)
        status = "succeeded" if all(r["status"] == "succeeded" for r in results.values()) else "failed"
        async with db.async_session_factory() as conn:
            changed = await background_outbox.finalize(conn, group_id, "running", status)
            if changed:
                summary = await conn.get(db.BackgroundGroupSummary, group_id)
                if summary and summary.status == "pending":
                    # Pure formatting: results are data, never instructions.
                    summary.text = json.dumps({"group_status": status, "steps": [
                        {"step_id": sid, "status": results[sid]["status"],
                         "result": results[sid]["result"]} for sid in sorted(results)
                    ]}, ensure_ascii=False)
                    summary.status = "succeeded"
            await conn.commit()
    except asyncio.CancelledError:
        if starting is not None:
            outcome = await asyncio.gather(starting, return_exceptions=True)
            if isinstance(outcome[0], str):
                running[sid] = outcome[0]
        for jid in running.values():
            await _cancel_job(jid)
        for sid in pending | running.keys():
            await _set_step(group_id, sid, status="cancelled", result="Cancelled")
        await _set_group(group_id, "cancelled")
        raise
    except Exception as exc:
        async def cleanup_failure(error):
            for jid in running.values():
                await _cancel_job(jid)
            for step_id in pending | running.keys():
                await _set_step(group_id, step_id, status="failed", result=str(error))
            await _set_group(group_id, "failed")
            async with db.async_session_factory() as conn:
                await conn.execute(update(db.BackgroundGroupSummary).where(db.BackgroundGroupSummary.group_id == group_id, db.BackgroundGroupSummary.status == "pending").values(status="failed"))
                await conn.commit()
        cleanup = asyncio.create_task(cleanup_failure(exc))
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await cleanup
            raise


async def _finish_cancel(group_id, job):
    if not job.done():
        job.cancel()
    await asyncio.gather(job, return_exceptions=True)
    async with db.async_session_factory() as conn:
        await conn.execute(update(db.BackgroundGroupStep).where(
            db.BackgroundGroupStep.group_id == group_id, db.BackgroundGroupStep.status.in_(("queued", "running"))
        ).values(status="cancelled", result="Cancelled", updated_at=db.utcnow()))
        await conn.execute(update(db.BackgroundGroupSummary).where(
            db.BackgroundGroupSummary.group_id == group_id, db.BackgroundGroupSummary.status == "pending"
        ).values(status="cancelled"))
        await background_outbox.finalize(conn, group_id, "cancelling", "cancelled")
        await conn.commit()


async def _cancel_owned(group_id, job):
    cancellation = _cancellations.get(group_id)
    if cancellation is None:
        cancellation = asyncio.create_task(_finish_cancel(group_id, job))
        _cancellations[group_id] = cancellation
        cancellation.add_done_callback(lambda _: _cancellations.pop(group_id, None))
    await asyncio.shield(cancellation)


async def _watch_cancel(group_id, job):
    # Keep the job reference even after its completion callback removes it.
    while True:
        try:
            async with db.async_session_factory() as conn:
                status = await conn.scalar(select(db.BackgroundGroup.status).where(
                    db.BackgroundGroup.id == group_id))
            if status == "cancelling":
                await _cancel_owned(group_id, job)
                return
            if job.done():
                async with db.async_session_factory() as conn:
                    status = await conn.scalar(select(db.BackgroundGroup.status).where(
                        db.BackgroundGroup.id == group_id))
                if status == "cancelling":
                    await _cancel_owned(group_id, job)
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(0.1)


async def cancel(context, group_id):
    scope = await background._scope(context)
    await background._recover_if_available()
    async with db.async_session_factory() as conn:
        await conn.execute(update(db.BackgroundGroup).where(
            db.BackgroundGroup.id == group_id, db.BackgroundGroup.user_id == scope[0],
            db.BackgroundGroup.session_id == scope[1], db.BackgroundGroup.branch_id == scope[2],
            db.BackgroundGroup.status.in_(("queued", "running"))
        ).values(status="cancelling", updated_at=db.utcnow()))
        await conn.commit()
    job = _groups.get(group_id)
    if job is not None:
        row = await get(context, group_id)
        if row["status"] == "cancelling":
            await _cancel_owned(group_id, job)
    return await get(context, group_id)


async def wait(context, group_id, timeout=30):
    deadline = asyncio.get_running_loop().time() + max(0, min(float(timeout), 60))
    while True:
        row = await get(context, group_id)
        if row["status"] not in ("queued", "running", "cancelling"):
            return row
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return row
        await asyncio.sleep(min(0.1, remaining))

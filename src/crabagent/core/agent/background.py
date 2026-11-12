"""Durable, explicitly collected background delegations (single process)."""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
import uuid

from sqlalchemy import select, update

from crabagent.core import database as db
from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.tools.registry import ToolRegistry

# The executor is deliberately single-process: other processes fail closed.
SAFE_TOOLS: frozenset[str] = frozenset({"read"})
MAX_ACTIVE_JOBS = 4
JOB_TIMEOUT_SECONDS = 300
_jobs: dict[str, asyncio.Task] = {}
_reservations: set[str] = set()
_cancellations: dict[str, asyncio.Task] = {}
_owner_file = None
_owner_pid = None
_recovery_task = None
_watcher_task = None


def owns_executor() -> bool:
    """True when this process holds the exclusive executor lock right now.

    The flock is released by the OS when the process dies, so holding it is the
    fencing token: a dead owner cannot write business state anymore.
    """
    return _owner_file is not None and _owner_pid == os.getpid()


def _claim_executor():
    global _owner_file, _owner_pid
    if _owner_file is not None and _owner_pid == os.getpid():
        return False
    if _owner_file is not None:
        _owner_file.close()
        _owner_file = None
    engine = db.async_session_factory.kw["bind"]
    database = engine.url.database
    if not database or database == ":memory:":
        raise ValueError("Background executor requires a file-backed database")
    handle = open(os.path.realpath(database) + ".background.lock", "a")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise ValueError("Background executor is owned by another process") from None
    _owner_file, _owner_pid = handle, os.getpid()
    return True


async def _ensure_executor():
    global _recovery_task, _watcher_task
    if _claim_executor() or _recovery_task is None:
        _recovery_task = asyncio.create_task(_interrupt_orphans())
    try:
        await asyncio.shield(_recovery_task)
    except Exception:
        _recovery_task = None
        raise
    if owns_executor():
        # Recreate the watcher when the running loop changed (tests use one
        # loop per test); in production there is a single loop.
        if _watcher_task is None or _watcher_task.get_loop() is not asyncio.get_running_loop():
            _watcher_task = asyncio.create_task(_watch_start_commands())


async def _interrupt_orphans():
    # Exclusive ownership proves that no previous executor can still run these jobs.
    async with db.async_session_factory() as conn:
        await conn.execute(update(db.BackgroundDelegation).where(
            db.BackgroundDelegation.status.in_(("queued", "running", "cancelling"))
        ).values(status="interrupted", result="Executor stopped before completion",
                 updated_at=db.utcnow()))
        # Publish only records whose groups are being interrupted in this transaction.
        await conn.execute(update(db.BackgroundDelivery).where(
            db.BackgroundDelivery.status == "authorized",
            db.BackgroundDelivery.group_id.in_(select(db.BackgroundGroup.id).where(
                db.BackgroundGroup.status.in_(("queued", "running", "cancelling"))))
        ).values(status="ready", terminal_status="interrupted"))
        await conn.execute(update(db.BackgroundGroup).where(
            db.BackgroundGroup.status.in_(("queued", "running", "cancelling"))
        ).values(status="interrupted", updated_at=db.utcnow()))
        await conn.execute(update(db.BackgroundGroupSummary).where(
            db.BackgroundGroupSummary.status == "pending"
        ).values(status="interrupted"))
        await conn.execute(update(db.BackgroundSemanticSummary).where(
            db.BackgroundSemanticSummary.status.in_(("pending", "running", "cancelling"))
        ).values(status="interrupted"))
        await conn.execute(update(db.BackgroundGroupStep).where(
            db.BackgroundGroupStep.status.in_(("queued", "running"))
        ).values(status="interrupted", result="Executor stopped before completion", updated_at=db.utcnow()))
        # Start commands queued for a previous owner are stale once this process
        # holds the lock: the records above were already interrupted here.
        await conn.execute(update(db.BackgroundStartCommand).where(
            db.BackgroundStartCommand.status.in_(("queued", "claimed"))
        ).values(status="interrupted", note="Executor stopped before completion", updated_at=db.utcnow()))
        await conn.commit()


async def _scope(context):
    if context is None:
        raise ValueError("Active authenticated session required")
    meta = context.metadata
    user, session, branch = meta.get("user_id"), meta.get("session_id"), meta.get("branch_id")
    if not isinstance(user, int) or isinstance(user, bool) or user <= 0 or not session or not branch:
        raise ValueError("Authenticated user, session and branch required")
    async with db.async_session_factory() as conn:
        owner = await conn.scalar(select(db.Conversation.id).where(
            db.Conversation.user_id == user, db.Conversation.session_id == session,
            db.Conversation.active_branch == branch,
        ))
    if owner is None:
        raise ValueError("Session or active branch unavailable")
    return user, session, branch


async def _authorize_start_transaction(conn, scope):
    """Serialize new work with changes to the authenticated active branch."""
    user, session, branch = scope
    changed = await conn.execute(update(db.Conversation).where(
        db.Conversation.user_id == user, db.Conversation.session_id == session,
        db.Conversation.active_branch == branch,
    ).values(active_branch=db.Conversation.active_branch))
    if not changed.rowcount:
        raise ValueError("Session or active branch unavailable")


def _where(scope, job_id):
    user, session, branch = scope
    return (db.BackgroundDelegation.id == job_id, db.BackgroundDelegation.user_id == user,
            db.BackgroundDelegation.session_id == session, db.BackgroundDelegation.branch_id == branch)


async def _recover_if_available():
    try:
        await _ensure_executor()
    except ValueError as exc:
        if str(exc) != "Background executor is owned by another process":
            raise


def _context_payload(context, agent_name, task, allowed_tools):
    """Serialize non-secret execution parameters for a forwarded start."""
    return json.dumps({
        "workspace": str(context.workspace),
        "model": context.model,
        "provider_name": context.provider_name,
        "max_iterations": context.max_iterations,
        "locale": context.locale,
        "agent_name": agent_name,
        "task": task,
        "allowed_tools": list(allowed_tools or []),
    }, ensure_ascii=False)


def _rebuild_context(payload, scope):
    """Rebuild the isolated sub-agent context from a validated payload."""
    from pathlib import Path

    workspace = payload.get("workspace")
    model = payload.get("model")
    provider_name = payload.get("provider_name")
    max_iterations = payload.get("max_iterations")
    locale = payload.get("locale") or "en"
    agent_name = payload.get("agent_name")
    task = payload.get("task")
    allowed_tools = payload.get("allowed_tools") or []
    if (not isinstance(workspace, str) or not workspace or not isinstance(agent_name, str)
            or not agent_name.strip() or not isinstance(task, str) or not task.strip()
            or not isinstance(allowed_tools, list)
            or any(not isinstance(name, str) for name in allowed_tools)
            or set(allowed_tools) - SAFE_TOOLS
            or not isinstance(max_iterations, int) or isinstance(max_iterations, bool)
            or max_iterations <= 0 or not isinstance(locale, str)):
        raise ValueError("Invalid forwarded payload")
    registry = ToolRegistry()
    if "read" in allowed_tools:
        from crabagent.core.agent.background_read import register_safe_read
        register_safe_read(registry)
    isolated = AgentContext(workspace=Path(workspace), tool_registry=registry,
                            model=model, provider_name=provider_name,
                            max_iterations=max_iterations, locale=locale)
    isolated.metadata.update(user_id=scope[0], session_id=scope[1], branch_id=scope[2], locale=locale)
    return isolated, agent_name, task


async def _forward_start(scope, context, agent_name, task, allowed_tools):
    """Persist an authorized start for the executor-owning process to claim."""
    payload = _context_payload(context, agent_name, task, allowed_tools)
    job_id = uuid.uuid4().hex
    async with db.async_session_factory() as conn:
        await _authorize_start_transaction(conn, scope)
        conn.add(db.BackgroundDelegation(id=job_id, user_id=scope[0], session_id=scope[1],
                 branch_id=scope[2], agent_name=agent_name, task=task, status="queued", result=""))
        conn.add(db.BackgroundStartCommand(id=uuid.uuid4().hex, kind="task", record_id=job_id,
                 user_id=scope[0], session_id=scope[1], branch_id=scope[2],
                 payload=payload, status="queued"))
        await conn.commit()
    return job_id


async def _execute_forwarded_task(row):
    payload = json.loads(row["payload"])
    isolated, agent_name, task = _rebuild_context(payload, (row["user_id"], row["session_id"], row["branch_id"]))
    async with db.async_session_factory() as conn:
        status = await conn.scalar(select(db.BackgroundDelegation.status).where(
            db.BackgroundDelegation.id == row["record_id"]))
    if status is None:
        raise ValueError("Forwarded task record missing")
    if status == "cancelling":
        # No coroutine was ever started here, so there is nothing to clean up.
        await _set(row["record_id"], "cancelled", "Cancelled", previous=("cancelling",))
        return
    if status != "queued":
        return
    if len(_reservations) >= MAX_ACTIVE_JOBS:
        raise ValueError("Background task capacity reached")
    job_id = row["record_id"]
    _reservations.add(job_id)
    job = asyncio.create_task(_run(job_id, isolated, agent_name, task))
    _jobs[job_id] = job

    def cleanup(_):
        _jobs.pop(job_id, None)
        _reservations.discard(job_id)
    job.add_done_callback(cleanup)
    asyncio.create_task(_watch_cancel(job_id, job))


async def _claim_next_command():
    async with db.async_session_factory() as conn:
        row = (await conn.scalars(select(db.BackgroundStartCommand).where(
            db.BackgroundStartCommand.status == "queued"
        ).order_by(db.BackgroundStartCommand.created_at).limit(1))).first()
        if row is None:
            return None
        changed = await conn.execute(update(db.BackgroundStartCommand).where(
            db.BackgroundStartCommand.id == row.id,
            db.BackgroundStartCommand.status == "queued",
        ).values(status="claimed", updated_at=db.utcnow()))
        await conn.commit()
        if not changed.rowcount:
            return None
        return {c: getattr(row, c) for c in
                ("id", "kind", "record_id", "user_id", "session_id", "branch_id", "payload")}


async def _finish_command(command_id, *, note=""):
    async with db.async_session_factory() as conn:
        await conn.execute(update(db.BackgroundStartCommand).where(
            db.BackgroundStartCommand.id == command_id,
            db.BackgroundStartCommand.status == "claimed",
        ).values(status="done", note=note, updated_at=db.utcnow()))
        await conn.commit()


async def _fail_command(row, note):
    async with db.async_session_factory() as conn:
        await conn.execute(update(db.BackgroundStartCommand).where(
            db.BackgroundStartCommand.id == row["id"],
            db.BackgroundStartCommand.status == "claimed",
        ).values(status="done", note=note, updated_at=db.utcnow()))
        if row["kind"] == "task":
            await conn.execute(update(db.BackgroundDelegation).where(
                db.BackgroundDelegation.id == row["record_id"],
                db.BackgroundDelegation.status == "queued",
            ).values(status="failed", result=note, updated_at=db.utcnow()))
        elif row["kind"] == "group":
            await conn.execute(update(db.BackgroundGroup).where(
                db.BackgroundGroup.id == row["record_id"],
                db.BackgroundGroup.status == "queued",
            ).values(status="failed", updated_at=db.utcnow()))
        elif row["kind"] == "semantic_summary":
            await conn.execute(update(db.BackgroundSemanticSummary).where(
                db.BackgroundSemanticSummary.group_id == row["record_id"],
                db.BackgroundSemanticSummary.status == "pending",
            ).values(status="failed", text=note))
        await conn.commit()


async def _execute_command(row):
    if row["kind"] == "task":
        await _execute_forwarded_task(row)
    elif row["kind"] == "group":
        from crabagent.core.agent import background_group
        await background_group.execute_forwarded(row)
    elif row["kind"] == "semantic_summary":
        from crabagent.core.agent import semantic_summary
        await semantic_summary.execute_forwarded(row)
    else:
        raise ValueError("Unknown command kind")


async def _run_next_command():
    # Capacity applies to task commands only; groups check their own budget.
    async with db.async_session_factory() as conn:
        head = (await conn.scalars(select(db.BackgroundStartCommand.kind).where(
            db.BackgroundStartCommand.status == "queued"
        ).order_by(db.BackgroundStartCommand.created_at).limit(1))).first()
    if head is None:
        return
    if head == "task" and len(_reservations) >= MAX_ACTIVE_JOBS:
        return
    row = await _claim_next_command()
    if row is None:
        return
    try:
        await _execute_command(row)
    except Exception as exc:
        await _fail_command(row, str(exc))
    else:
        await _finish_command(row["id"])


async def _watch_start_commands():
    """Executor loop: claim persisted start commands while holding the lock.

    Ownership of the flock is the fence. When this process dies the OS releases
    the lock and its coroutines die with it, so a stale executor cannot write.
    """
    while True:
        await asyncio.sleep(0.2)
        if not owns_executor():
            return
        try:
            await _run_next_command()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Individual command failures are recorded by _run_next_command;
            # transport-level errors just retry on the next tick.
            continue


async def get(context, job_id):
    scope = await _scope(context)
    await _recover_if_available()
    async with db.async_session_factory() as conn:
        row = await conn.scalar(select(db.BackgroundDelegation).where(*_where(scope, job_id)))
        if row is None:
            raise ValueError("Task not found")
        return {k: getattr(row, k) for k in ("id", "agent_name", "task", "status", "result")}


async def list_tasks(context):
    user, session, branch = await _scope(context)
    await _recover_if_available()
    async with db.async_session_factory() as conn:
        rows = (await conn.scalars(select(db.BackgroundDelegation).where(
            db.BackgroundDelegation.user_id == user,
            db.BackgroundDelegation.session_id == session,
            db.BackgroundDelegation.branch_id == branch,
        ).order_by(db.BackgroundDelegation.created_at.desc()).limit(100))).all()
        return [{k: getattr(row, k) for k in ("id", "agent_name", "task", "status")} for row in rows]


async def start(context, agent_name, task, allowed_tools=None, *, _group_step=None, _scope_override=None):
    scope = _scope_override if _scope_override is not None else await _scope(context)
    if context.metadata.get("_sub_agent_depth", 0):
        raise ValueError("Nested background delegation is disabled")
    if not agent_name.strip() or not task.strip():
        raise ValueError("Agent and task are required")
    from crabagent.core.agent.agents import get_agent
    agent_def = await get_agent(agent_name)
    if not agent_def:
        raise ValueError("Agent not found")
    if allowed_tools is None:
        allowed_tools = []
    if not isinstance(allowed_tools, list) or any(not isinstance(name, str) for name in allowed_tools):
        raise ValueError("allowed_tools must be a list of tool names")
    if set(allowed_tools) - SAFE_TOOLS:
        raise ValueError("Unsupported background tool")
    registry = ToolRegistry()
    if "read" in allowed_tools:
        from crabagent.core.agent.background_read import register_safe_read
        from crabagent.core.agent.tools.read import read_file
        parent_tool = context.tool_registry.get("read")
        if (not parent_tool or parent_tool.handler is not read_file or parent_tool.requires_permission
                or context.tool_permissions.get("read", "auto") != "auto"
                or agent_def.get("tool_permissions", {}).get("read", "auto") != "auto"):
            raise ValueError("Background read requires automatic parent and agent permission")
        register_safe_read(registry)
    isolated = AgentContext(workspace=context.workspace, tool_registry=registry,
                            model=context.model, provider_name=context.provider_name,
                            max_iterations=context.max_iterations, locale=context.locale)
    isolated.metadata.update(user_id=scope[0], session_id=scope[1], branch_id=scope[2], locale=context.locale)
    try:
        await _ensure_executor()
    except ValueError as exc:
        # Another process owns the executor: forward the authorized start as a
        # durable command instead of failing. Group steps always run on the
        # owning process, so they never take this path.
        if str(exc) != "Background executor is owned by another process" or _group_step is not None:
            raise
        return await _forward_start(scope, context, agent_name, task, allowed_tools)
    if len(_reservations) >= MAX_ACTIVE_JOBS:
        raise ValueError("Background task capacity reached")
    job_id = uuid.uuid4().hex
    _reservations.add(job_id)
    try:
        async with db.async_session_factory() as conn:
            if _scope_override is None:
                await _authorize_start_transaction(conn, scope)
            conn.add(db.BackgroundDelegation(id=job_id, user_id=scope[0], session_id=scope[1],
                     branch_id=scope[2], agent_name=agent_name, task=task, status="queued", result=""))
            if _group_step is not None:
                group_id, step_id = _group_step
                active = await conn.execute(update(db.BackgroundGroup).where(
                    db.BackgroundGroup.id == group_id, db.BackgroundGroup.status == "running"
                ).values(updated_at=db.utcnow()))
                if not active.rowcount:
                    raise ValueError("Group is no longer running")
                changed = await conn.execute(update(db.BackgroundGroupStep).where(
                    db.BackgroundGroupStep.group_id == group_id, db.BackgroundGroupStep.step_id == step_id,
                    db.BackgroundGroupStep.status == "queued"
                ).values(job_id=job_id, status="running", updated_at=db.utcnow()))
                if not changed.rowcount:
                    raise ValueError("Group step is no longer queued")
            await conn.commit()
        job = asyncio.create_task(_run(job_id, isolated, agent_name, task))
        _jobs[job_id] = job
        def cleanup(_):
            _jobs.pop(job_id, None)
            _reservations.discard(job_id)
        job.add_done_callback(cleanup)
        asyncio.create_task(_watch_cancel(job_id, job))
    except BaseException:
        _reservations.discard(job_id)
        raise
    return job_id



async def _set(job_id, status, result="", previous=("queued", "running")):
    async with db.async_session_factory() as conn:
        changed = await conn.execute(update(db.BackgroundDelegation).where(
            db.BackgroundDelegation.id == job_id, db.BackgroundDelegation.status.in_(previous)
        ).values(status=status, result=result, updated_at=db.utcnow()))
        await conn.commit()
        return bool(changed.rowcount)


async def _run(job_id, context, agent_name, task):
    from crabagent.core.agent.agents import BackgroundAgentResult, spawn_sub_agent
    try:
        if not await _set(job_id, "running", previous=("queued",)):
            return
        result = await asyncio.wait_for(
            spawn_sub_agent(agent_name, task, context, background=True), timeout=JOB_TIMEOUT_SECONDS
        )
        if not isinstance(result, BackgroundAgentResult) or result.status not in ("succeeded", "failed"):
            raise TypeError("Invalid background agent result")
        await _set(job_id, result.status, result.result)
    except TimeoutError:
        await _set(job_id, "failed", "Background task timed out")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await _set(job_id, "failed", str(exc))


async def wait(context, job_id, timeout=30):
    deadline = asyncio.get_running_loop().time() + max(0, min(float(timeout), 60))
    while True:
        row = await get(context, job_id)
        if row["status"] not in ("queued", "running", "cancelling"):
            return row
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return row
        await asyncio.sleep(min(0.1, remaining))


async def _finish_cancel(job_id, job):
    await _set(job_id, "cancelling", "Cancellation in progress")
    if not job.done():
        job.cancel()
    await asyncio.gather(job, return_exceptions=True)
    await _set(job_id, "cancelled", "Cancelled", previous=("cancelling",))


async def _cancel_owned(job_id):
    cancellation = _cancellations.get(job_id)
    if cancellation is None:
        job = _jobs.get(job_id)
        if job is None:
            raise ValueError("Task is not owned by this process; cancellation unavailable")
        cancellation = asyncio.create_task(_finish_cancel(job_id, job))
        _cancellations[job_id] = cancellation
        cancellation.add_done_callback(lambda _: _cancellations.pop(job_id, None))
    await asyncio.shield(cancellation)


async def _watch_cancel(job_id, job):
    # Only the owning process can confirm that its coroutine has stopped.
    while True:
        try:
            async with db.async_session_factory() as conn:
                status = await conn.scalar(select(db.BackgroundDelegation.status).where(
                    db.BackgroundDelegation.id == job_id))
            if status == "cancelling":
                if job_id in _jobs or job_id in _cancellations:
                    await _cancel_owned(job_id)
                else:
                    await _finish_cancel(job_id, job)
                return
            if job.done():
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            # Retry transient database failures while the job remains active.
            pass
        await asyncio.sleep(0.1)


async def cancel(context, job_id):
    scope = await _scope(context)
    await _recover_if_available()
    async with db.async_session_factory() as conn:
        await conn.execute(update(db.BackgroundDelegation).where(
            *_where(scope, job_id),
            db.BackgroundDelegation.status.in_(("queued", "running"))
        ).values(status="cancelling", result="Cancellation in progress", updated_at=db.utcnow()))
        await conn.commit()
    if job_id in _jobs:
        await _cancel_owned(job_id)
    return await get(context, job_id)


def format_result(row):
    # Results are untrusted data and are delivered only as explicit tool responses.
    return json.dumps(row, ensure_ascii=False)


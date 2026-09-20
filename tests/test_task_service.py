"""Tests for trusted work system Phase 1: Task ↔ Run service + startup recovery."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core.database import Base
from crabagent.core.task import service as task_service
from crabagent.core.task import store as task_store
from crabagent.core.task.recovery import recover_interrupted_state


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_add_task_classifies_owner(db):
    t1 = await task_store.add_task(db, user_id=1, title="agent work", assignee="crabagent")
    assert t1["owner_type"] == "agent"
    assert t1["owner_name"] == "CrabAgent"

    t2 = await task_store.add_task(db, user_id=1, title="human work", assignee="xcl")
    assert t2["owner_type"] == "human"
    assert t2["owner_name"] == "xcl"

    t3 = await task_store.add_task(db, user_id=1, title="no assignee")
    assert t3["owner_type"] == "human"
    assert t3["verification_status"] == "unverified"


@pytest.mark.asyncio
async def test_start_agent_run_links_run_and_task(db):
    task = await task_store.add_task(db, user_id=1, title="生成报告")

    updated, run_id = await task_service.start_agent_run(
        db, task["id"], 1, agent_name="main", session_id="sess-1", phase="读取数据"
    )

    assert updated["status"] == "in_progress"
    assert updated["active_run_id"] == run_id
    assert updated["last_run_id"] == run_id
    assert updated["started_at"] is not None

    runs = await task_service.list_task_runs(db, task["id"], 1)
    assert len(runs) == 1
    assert runs[0]["task_id"] == task["id"]
    assert runs[0]["status"] == "running"
    assert runs[0]["phase"] == "读取数据"


@pytest.mark.asyncio
async def test_start_agent_run_missing_task_raises(db):
    with pytest.raises(LookupError):
        await task_service.start_agent_run(db, 999, 1)


@pytest.mark.asyncio
async def test_finish_run_completed_marks_task_done(db):
    task = await task_store.add_task(db, user_id=1, title="生成报告")
    _, run_id = await task_service.start_agent_run(db, task["id"], 1)

    updated = await task_service.finish_agent_run(
        db, run_id, 1, "completed", result_summary="报告已生成", tokens_used=120
    )

    assert updated["status"] == "done"
    assert updated["active_run_id"] is None
    assert updated["completed_at"] is not None
    assert updated["result_summary"] == "报告已生成"


@pytest.mark.asyncio
async def test_finish_run_failed_marks_task_failed(db):
    task = await task_store.add_task(db, user_id=1, title="生成报告")
    _, run_id = await task_service.start_agent_run(db, task["id"], 1)

    updated = await task_service.finish_agent_run(db, run_id, 1, "failed", error="API 超时")

    assert updated["status"] == "failed"
    assert "API 超时" in updated["warning_summary"]


@pytest.mark.asyncio
async def test_finish_run_cancelled_after_done_keeps_done(db):
    task = await task_store.add_task(db, user_id=1, title="生成报告")
    _, run_id = await task_service.start_agent_run(db, task["id"], 1)
    # A summary-only task completes as done under trusted judgment.
    await task_service.finish_agent_run(db, run_id, 1, "completed", result_summary="报告完成")

    # A late cancellation arriving after done must not downgrade the task.
    updated = await task_service.finish_agent_run(db, run_id, 1, "cancelled")

    assert updated is not None
    assert updated["status"] == "done"


@pytest.mark.asyncio
async def test_cancel_task_finalizes_active_run(db):
    task = await task_store.add_task(db, user_id=1, title="生成报告")
    _, run_id = await task_service.start_agent_run(db, task["id"], 1)

    updated = await task_service.cancel_task(db, task["id"], 1, reason="用户停止")

    assert updated["status"] == "cancelled"
    runs = await task_service.list_task_runs(db, task["id"], 1)
    assert runs[0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_mark_result_viewed(db):
    task = await task_store.add_task(db, user_id=1, title="生成报告")

    updated = await task_service.mark_result_viewed(db, task["id"], 1)

    assert updated["result_viewed_at"] is not None


@pytest.mark.asyncio
async def test_recovery_interrupts_zombie_runs_and_tasks(db):
    task = await task_store.add_task(db, user_id=1, title="生成报告")
    _, run_id = await task_service.start_agent_run(db, task["id"], 1)

    summary = await recover_interrupted_state(db)

    assert summary["interrupted_runs"] == 1
    runs = await task_service.list_task_runs(db, task["id"], 1)
    assert runs[0]["status"] == "interrupted"
    assert runs[0]["interrupted_reason"]

    task_after = await task_store.get_task(db, task["id"], 1)
    assert task_after["status"] == "failed"  # no result summary → failed
    assert task_after["active_run_id"] is None


@pytest.mark.asyncio
async def test_recovery_with_partial_result_marks_partial(db):
    task = await task_store.add_task(db, user_id=1, title="生成报告")
    await task_service.start_agent_run(db, task["id"], 1)
    await task_store.update_task(db, task["id"], 1, result_summary="Excel 汇总已生成，Word 未完成")

    summary = await recover_interrupted_state(db)

    assert summary["partial_tasks"] == 1
    task_after = await task_store.get_task(db, task["id"], 1)
    assert task_after["status"] == "partial"


@pytest.mark.asyncio
async def test_recovery_is_idempotent(db):
    task = await task_store.add_task(db, user_id=1, title="生成报告")
    await task_service.start_agent_run(db, task["id"], 1)

    first = await recover_interrupted_state(db)
    second = await recover_interrupted_state(db)

    assert any(first.values())
    assert second == {
        "interrupted_runs": 0,
        "partial_tasks": 0,
        "failed_tasks": 0,
        "expired_requests": 0,
    }

"""Tests for the unified attention service (trusted work system Phase 4)."""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core.database import Base
from crabagent.core.task import attention
from crabagent.core.task import request_service as rs
from crabagent.core.task import service as task_service
from crabagent.core.task import store as task_store


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
async def test_idle_when_nothing_happens(db):
    summary = await attention.get_attention_summary(db, 1)

    assert summary["status"] == "idle"
    assert summary["count"] == 0
    assert all(not items for items in summary["groups"].values())


@pytest.mark.asyncio
async def test_pending_request_outranks_everything(db):
    failed = await task_store.add_task(db, user_id=1, title="失败任务")
    await task_store.update_task(db, failed["id"], 1, status="failed")
    task = await task_store.add_task(db, user_id=1, title="发邮件")
    await rs.create_request(db, user_id=1, request_type="approval", title="确认发送", task_id=task["id"])

    summary = await attention.get_attention_summary(db, 1)

    assert summary["status"] == "pending_requests"
    assert summary["priority"] == attention.PENDING_REQUESTS
    assert summary["target"]["type"] == "task_request"
    assert summary["target"]["request_id"]
    assert len(summary["groups"]["failed_tasks"]) == 1


@pytest.mark.asyncio
async def test_unread_results_appear_until_viewed(db):
    task = await task_store.add_task(db, user_id=1, title="写报告")
    _, run_id = await task_service.start_agent_run(db, task["id"], 1)
    await task_service.finish_agent_run(db, run_id, 1, "completed", result_summary="报告完成")

    summary = await attention.get_attention_summary(db, 1)
    assert len(summary["groups"]["unread_results"]) == 1

    await task_service.mark_result_viewed(db, task["id"], 1)
    summary = await attention.get_attention_summary(db, 1)
    assert not summary["groups"]["unread_results"]


@pytest.mark.asyncio
async def test_active_runs_and_partial_tasks_grouped(db):
    running = await task_store.add_task(db, user_id=1, title="进行中")
    await task_service.start_agent_run(db, running["id"], 1)
    # in_progress without a live run (e.g. waiting for a resume) also counts
    lingering = await task_store.add_task(db, user_id=1, title="待续跑")
    await task_store.update_task(db, lingering["id"], 1, status="in_progress")

    partial = await task_store.add_task(db, user_id=1, title="部分完成")
    await task_store.update_task(db, partial["id"], 1, status="partial")

    summary = await attention.get_attention_summary(db, 1)

    # one running-run item (dedup: the run's task is not double-counted)
    # + one in_progress task without a run
    assert len(summary["groups"]["active_runs"]) == 2
    assert len(summary["groups"]["partial_tasks"]) == 1
    # partial (priority 3) outranks active runs (priority 4)
    assert summary["status"] == "partial_tasks"


@pytest.mark.asyncio
async def test_due_human_tasks_within_24h(db):
    soon = await task_store.add_task(
        db,
        user_id=1,
        title="明天截止",
        deadline=datetime.datetime.now() + datetime.timedelta(hours=12),
    )
    # assignee "xcl" → human owner
    far = await task_store.add_task(
        db,
        user_id=1,
        title="远期截止",
        assignee="xcl",
        deadline=datetime.datetime.now() + datetime.timedelta(days=7),
    )

    summary = await attention.get_attention_summary(db, 1)

    due_titles = {item["message"] for item in summary["groups"]["due_human_tasks"]}
    assert any("明天截止" in m for m in due_titles)
    assert not any("远期截止" in m for m in due_titles)
    assert far["owner_type"] == "human"
    assert soon["id"] != far["id"]


@pytest.mark.asyncio
async def test_attention_by_workspace(db):
    task_a = await task_store.add_task(db, user_id=1, title="A 任务", workspace="工作区A")
    await task_store.update_task(db, task_a["id"], 1, status="failed")
    task_b = await task_store.add_task(db, user_id=1, title="B 任务", workspace="工作区B")
    await task_service.start_agent_run(db, task_b["id"], 1)

    by_ws = await attention.get_attention_by_workspace(db, 1)

    assert len(by_ws) == 2
    # 工作区A (failed, priority 1) ranks above 工作区B (working, priority 4)
    assert by_ws[0]["workspace"] == "工作区A"
    assert by_ws[0]["status"] == "failed"
    assert by_ws[1]["status"] == "working"

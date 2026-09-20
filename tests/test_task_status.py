"""Tests for centralized task status semantics (trusted work system Phase 0)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core.database import Base
from crabagent.core.task import store as task_store
from crabagent.core.task.status import (
    ACTIVE_TASK_STATUSES,
    CLOSED_TASK_STATUSES,
    OPEN_TASK_STATUSES,
    TASK_STATUS_VALUES,
    USER_ACTIONABLE_TASK_STATUSES,
    validate_task_status,
)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def test_status_collections_are_consistent():
    assert OPEN_TASK_STATUSES == (
        "pending",
        "in_progress",
        "waiting_user",
        "partial",
        "failed",
    )
    assert CLOSED_TASK_STATUSES == ("done", "cancelled")
    assert set(OPEN_TASK_STATUSES) | set(CLOSED_TASK_STATUSES) == set(TASK_STATUS_VALUES)
    # No overlap between open and closed
    assert not set(OPEN_TASK_STATUSES) & set(CLOSED_TASK_STATUSES)
    # User-actionable and active subsets live inside open statuses
    assert set(USER_ACTIONABLE_TASK_STATUSES) <= set(OPEN_TASK_STATUSES)
    assert set(ACTIVE_TASK_STATUSES) <= set(OPEN_TASK_STATUSES)


def test_validate_task_status_accepts_known_and_rejects_unknown():
    for status in TASK_STATUS_VALUES:
        assert validate_task_status(status) == status
    with pytest.raises(ValueError, match="Invalid task status"):
        validate_task_status("queued")


@pytest.mark.asyncio
async def test_new_task_defaults_to_pending(db):
    t = await task_store.add_task(db, user_id=1, title="写报告")

    assert t["status"] == "pending"


@pytest.mark.asyncio
async def test_update_task_rejects_invalid_status(db):
    t = await task_store.add_task(db, user_id=1, title="写报告")

    with pytest.raises(ValueError, match="Invalid task status"):
        await task_store.update_task(db, t["id"], 1, status="planning")


@pytest.mark.asyncio
async def test_update_task_accepts_new_semantic_statuses(db):
    t = await task_store.add_task(db, user_id=1, title="写报告")

    t = await task_store.update_task(db, t["id"], 1, status="waiting_user")
    assert t["status"] == "waiting_user"
    t = await task_store.update_task(db, t["id"], 1, status="partial")
    assert t["status"] == "partial"


@pytest.mark.asyncio
async def test_pending_filter_includes_open_semantic_statuses(db):
    for status in ("pending", "in_progress", "waiting_user", "partial", "failed"):
        await task_store.add_task(db, user_id=1, title=f"t-{status}")
    await task_store.add_task(db, user_id=1, title="t-done")
    # mark the last one done
    tasks = await task_store.list_tasks(db, 1, "all")
    done_id = next(t_["id"] for t_ in tasks if t_["title"] == "t-done")
    await task_store.update_task(db, done_id, 1, status="done")

    pending = await task_store.list_tasks(db, 1, "pending")
    titles = {t_["title"] for t_ in pending}
    assert titles == {"t-pending", "t-in_progress", "t-waiting_user", "t-partial", "t-failed"}

    done = await task_store.list_tasks(db, 1, "done")
    assert [t_["title"] for t_ in done] == ["t-done"]


@pytest.mark.asyncio
async def test_summary_counts_open_statuses(db):
    await task_store.add_task(db, user_id=1, title="open-1")
    t = await task_store.add_task(db, user_id=1, title="will-done")
    await task_store.update_task(db, t["id"], 1, status="done")

    summary = await task_store.get_task_summary(db, 1)
    assert summary["total"] == 2
    assert summary["pending"] == 1

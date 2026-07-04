"""Tests for task store CRUD operations."""
from __future__ import annotations

import datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core.database import Base
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
async def test_add_task(db):
    result = await task_store.add_task(
        db, user_id=1, title="Write report", priority="high", project="Q3",
    )

    assert result["title"] == "Write report"
    assert result["priority"] == "high"
    assert result["status"] == "pending"
    assert result["project"] == "Q3"
    assert "id" in result


@pytest.mark.asyncio
async def test_add_task_with_deadline(db):
    deadline = datetime.datetime(2026, 8, 1, 12, 0)
    result = await task_store.add_task(db, user_id=1, title="Task", deadline=deadline)

    assert result["deadline"] is not None


@pytest.mark.asyncio
async def test_list_tasks_filters_by_status(db):
    await task_store.add_task(db, user_id=1, title="pending task")
    done_task = await task_store.add_task(db, user_id=1, title="done task")
    await task_store.update_task(db, done_task["id"], 1, status="done")

    pending = await task_store.list_tasks(db, user_id=1, status_filter="pending")
    done = await task_store.list_tasks(db, user_id=1, status_filter="done")
    all_tasks = await task_store.list_tasks(db, user_id=1, status_filter="all")

    assert len(pending) == 1
    assert len(done) == 1
    assert len(all_tasks) == 2


@pytest.mark.asyncio
async def test_list_tasks_filters_by_project(db):
    await task_store.add_task(db, user_id=1, title="A", project="Alpha")
    await task_store.add_task(db, user_id=1, title="B", project="Beta")

    alpha = await task_store.list_tasks(db, user_id=1, status_filter="all", project="Alpha")
    assert len(alpha) == 1
    assert alpha[0]["title"] == "A"


@pytest.mark.asyncio
async def test_update_task_changes_fields(db):
    task = await task_store.add_task(db, user_id=1, title="Original")
    updated = await task_store.update_task(
        db, task["id"], 1, title="Changed", priority="low", status="in_progress",
    )

    assert updated["title"] == "Changed"
    assert updated["priority"] == "low"
    assert updated["status"] == "in_progress"


@pytest.mark.asyncio
async def test_update_task_returns_none_for_missing(db):
    result = await task_store.update_task(db, 99999, 1, title="X")
    assert result is None


@pytest.mark.asyncio
async def test_delete_task(db):
    task = await task_store.add_task(db, user_id=1, title="Temp")
    ok = await task_store.delete_task(db, task["id"], 1)
    assert ok is True

    remaining = await task_store.list_tasks(db, user_id=1, status_filter="all")
    assert len(remaining) == 0


@pytest.mark.asyncio
async def test_delete_task_returns_false_for_missing(db):
    ok = await task_store.delete_task(db, 99999, 1)
    assert ok is False


@pytest.mark.asyncio
async def test_list_projects(db):
    await task_store.add_task(db, user_id=1, title="A", project="Alpha")
    await task_store.add_task(db, user_id=1, title="B", project="Beta")
    await task_store.add_task(db, user_id=1, title="C", project="Alpha")

    projects = await task_store.list_projects(db, user_id=1)
    names = [p["name"] for p in projects]
    assert "Alpha" in names
    assert "Beta" in names

    alpha = next(p for p in projects if p["name"] == "Alpha")
    assert alpha["task_count"] == 2


@pytest.mark.asyncio
async def test_get_task_summary(db):
    await task_store.add_task(db, user_id=1, title="pending 1")
    await task_store.add_task(db, user_id=1, title="pending 2")
    done = await task_store.add_task(db, user_id=1, title="done 1")
    await task_store.update_task(db, done["id"], 1, status="done")

    summary = await task_store.get_task_summary(db, user_id=1)

    assert summary["total"] >= 3
    assert summary["pending"] >= 2
    assert summary["done_today"] >= 1
    assert summary["overdue"] == 0


@pytest.mark.asyncio
async def test_list_tasks_due_soon(db):
    now = datetime.datetime.now()
    await task_store.add_task(
        db, user_id=1, title="due soon", deadline=now + datetime.timedelta(hours=12),
    )
    await task_store.add_task(
        db, user_id=1, title="far future", deadline=now + datetime.timedelta(days=30),
    )

    due_soon = await task_store.list_tasks_due_soon(db, user_id=1, within_hours=24)

    assert len(due_soon) == 1
    assert due_soon[0]["title"] == "due soon"


@pytest.mark.asyncio
async def test_extract_keywords():
    keywords = task_store._extract_keywords(["Fix login bug", "Fix signup bug", "Update docs"])
    assert "fix" in keywords
    assert "bug" in keywords

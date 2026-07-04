"""Tests for calendar store CRUD."""
from __future__ import annotations

import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from crabagent.core.database import Base
from crabagent.core.calendar import store as cal_store


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
async def test_add_event(db):
    result = await cal_store.add_event(
        db,
        user_id=1,
        title="Team Meeting",
        start_time=datetime.datetime(2026, 7, 1, 14, 0),
        end_time=datetime.datetime(2026, 7, 1, 15, 0),
        all_day=False,
        location="Room A",
        project="Q3",
        reminder_minutes=10,
    )

    assert result["title"] == "Team Meeting"
    assert result["location"] == "Room A"
    assert "id" in result


@pytest.mark.asyncio
async def test_list_events_in_range(db):
    await cal_store.add_event(
        db, user_id=1, title="July 1",
        start_time=datetime.datetime(2026, 7, 1, 10, 0),
    )
    await cal_store.add_event(
        db, user_id=1, title="July 15",
        start_time=datetime.datetime(2026, 7, 15, 10, 0),
    )
    await cal_store.add_event(
        db, user_id=1, title="August 1",
        start_time=datetime.datetime(2026, 8, 1, 10, 0),
    )

    events = await cal_store.list_events(
        db, user_id=1,
        start=datetime.datetime(2026, 7, 1),
        end=datetime.datetime(2026, 7, 31, 23, 59),
    )

    titles = [e["title"] for e in events]
    assert "July 1" in titles
    assert "July 15" in titles
    assert "August 1" not in titles


@pytest.mark.asyncio
async def test_update_event(db):
    event = await cal_store.add_event(
        db, user_id=1, title="Original",
        start_time=datetime.datetime(2026, 7, 1, 10, 0),
    )
    updated = await cal_store.update_event(
        db, event["id"], 1, title="Updated", location="Room B",
    )

    assert updated["title"] == "Updated"
    assert updated["location"] == "Room B"


@pytest.mark.asyncio
async def test_update_event_returns_none_for_missing(db):
    result = await cal_store.update_event(db, 99999, 1, title="X")
    assert result is None


@pytest.mark.asyncio
async def test_delete_event(db):
    event = await cal_store.add_event(
        db, user_id=1, title="To Delete",
        start_time=datetime.datetime(2026, 7, 1, 10, 0),
    )
    ok = await cal_store.delete_event(db, event["id"], 1)
    assert ok is True

    # Verify deleted
    remaining = await cal_store.list_events(
        db, user_id=1,
        start=datetime.datetime(2026, 7, 1),
        end=datetime.datetime(2026, 7, 2),
    )
    assert all(e["title"] != "To Delete" for e in remaining)


@pytest.mark.asyncio
async def test_delete_event_returns_false_for_missing(db):
    ok = await cal_store.delete_event(db, 99999, 1)
    assert ok is False

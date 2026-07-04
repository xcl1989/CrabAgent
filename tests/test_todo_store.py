"""Tests for todo store CRUD."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core.database import Base
from crabagent.core.todo import store as todo_store


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
async def test_add_todo(db):
    result = await todo_store.add_todo(db, session_id="s1", task="Write tests")

    assert result["task"] == "Write tests"
    assert result["done"] is False
    assert "id" in result


@pytest.mark.asyncio
async def test_list_todos(db):
    await todo_store.add_todo(db, session_id="s1", task="task 1")
    await todo_store.add_todo(db, session_id="s1", task="task 2")
    await todo_store.add_todo(db, session_id="s2", task="other")

    todos = await todo_store.list_todos(db, session_id="s1")
    assert len(todos) == 2


@pytest.mark.asyncio
async def test_list_todos_filter_done(db):
    t = await todo_store.add_todo(db, session_id="s1", task="task 1")
    await todo_store.mark_done(db, t["id"], "s1")
    await todo_store.add_todo(db, session_id="s1", task="task 2")

    done = await todo_store.list_todos(db, session_id="s1", filter_="done")
    all_todos = await todo_store.list_todos(db, session_id="s1", filter_="all")

    assert len(done) == 1
    assert len(all_todos) == 2


@pytest.mark.asyncio
async def test_mark_done(db):
    t = await todo_store.add_todo(db, session_id="s1", task="do thing")
    ok = await todo_store.mark_done(db, t["id"], "s1")
    assert ok is True

    done = await todo_store.list_todos(db, session_id="s1", filter_="done")
    assert done[0]["task"] == "do thing"


@pytest.mark.asyncio
async def test_mark_done_returns_false_for_missing(db):
    ok = await todo_store.mark_done(db, 99999, "s1")
    assert ok is False


@pytest.mark.asyncio
async def test_delete_todo(db):
    t = await todo_store.add_todo(db, session_id="s1", task="temp")
    ok = await todo_store.delete_todo(db, t["id"], "s1")
    assert ok is True

    todos = await todo_store.list_todos(db, session_id="s1")
    assert len(todos) == 0


@pytest.mark.asyncio
async def test_delete_todo_returns_false_for_missing(db):
    ok = await todo_store.delete_todo(db, 99999, "s1")
    assert ok is False

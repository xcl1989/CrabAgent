"""Tests for shared workspace store."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core.database import Base, SharedMemory


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def test_shared_memory_model_fields():
    """Verify SharedMemory model exists and has expected columns."""
    assert "shared_memory" in Base.metadata.tables
    table = Base.metadata.tables["shared_memory"]
    assert "session_id" in table.columns
    assert "key" in table.columns
    assert "value" in table.columns
    assert "author" in table.columns


@pytest.mark.asyncio
async def test_shared_memory_crud(db):
    item = SharedMemory(session_id="s1", key="findings", value="test data", author="agent")
    db.add(item)
    await db.commit()

    from sqlalchemy import select

    result = await db.execute(select(SharedMemory).where(SharedMemory.session_id == "s1"))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].key == "findings"
    assert rows[0].value == "test data"
    assert rows[0].author == "agent"

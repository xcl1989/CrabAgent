"""Tests for the ensure_column migration helper in init_db."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from crabagent.core.database import ensure_column


@pytest.fixture
async def conn():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as c:
        await c.execute(text("CREATE TABLE demo (id INTEGER PRIMARY KEY, name TEXT)"))
        yield c
    await engine.dispose()


async def test_ensure_column_adds_missing_column(conn):
    added = await ensure_column(conn, "demo", "owner_type", "VARCHAR(20) DEFAULT 'human'")

    assert added is True
    result = await conn.execute(text("PRAGMA table_info(demo)"))
    columns = [row[1] for row in result.fetchall()]
    assert "owner_type" in columns


async def test_ensure_column_is_idempotent(conn):
    await ensure_column(conn, "demo", "phase", "VARCHAR(200) DEFAULT ''")

    added_again = await ensure_column(conn, "demo", "phase", "VARCHAR(200) DEFAULT ''")

    assert added_again is False


async def test_ensure_column_ignores_special_column_names(conn):
    # Column names/tables come from internal constants; this guards against
    # accidental SQL injection through the helper's f-strings.
    with pytest.raises(Exception):
        await ensure_column(conn, "demo; DROP TABLE demo", "x", "TEXT")


@pytest.mark.asyncio
async def test_collaboration_tables_add_to_existing_database(tmp_path):
    from crabagent.core.database import Base

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE existing_data (value TEXT)"))
        await connection.execute(text("INSERT INTO existing_data VALUES ('keep')"))
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(Base.metadata.create_all)
        assert (await connection.execute(text("SELECT value FROM existing_data"))).scalar_one() == "keep"
        result = await connection.execute(text("SELECT name FROM sqlite_master WHERE name='collaboration_projects'"))
        assert result.scalar_one() == "collaboration_projects"
    await engine.dispose()

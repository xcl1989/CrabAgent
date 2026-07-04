"""Tests for molt snapshot store."""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core.database import Base, Molt
from crabagent.core.molt import store as molt_store


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
async def test_create_molt_inserts_row(db):
    result = await molt_store.create_molt(
        db,
        molt_id="molt_0001",
        session_id="sess1",
        branch_id="main",
        description="test snapshot",
        method="git",
        file_count=3,
    )

    assert result["molt_id"] == "molt_0001"
    assert result["description"] == "test snapshot"
    assert result["file_count"] == 3


@pytest.mark.asyncio
async def test_list_molts_returns_sorted(db):
    await molt_store.create_molt(db, molt_id="molt_0002", session_id="s1", branch_id="main", description="second", method="git", file_count=1)
    await molt_store.create_molt(db, molt_id="molt_0001", session_id="s1", branch_id="main", description="first", method="git", file_count=1)

    molts = await molt_store.list_molts(db, session_id="s1")

    assert len(molts) >= 2
    ids = [m["molt_id"] for m in molts]
    assert "molt_0001" in ids
    assert "molt_0002" in ids


@pytest.mark.asyncio
async def test_get_molt_returns_none_for_missing(db):
    result = await molt_store.get_molt(db, "nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_molt_returns_row(db):
    await molt_store.create_molt(db, molt_id="molt_x", session_id="s1", branch_id="main", description="x", method="git", file_count=0)

    result = await molt_store.get_molt(db, "molt_x")
    assert result is not None
    assert result["description"] == "x"


@pytest.mark.asyncio
async def test_count_molts(db):
    await molt_store.create_molt(db, molt_id="molt_a", session_id="s1", branch_id="main", description="a", method="git", file_count=0)
    await molt_store.create_molt(db, molt_id="molt_b", session_id="s1", branch_id="main", description="b", method="git", file_count=0)

    count = await molt_store.count_molts(db, "s1")
    assert count == 2


@pytest.mark.asyncio
async def test_delete_molt(db):
    await molt_store.create_molt(db, molt_id="molt_d", session_id="s1", branch_id="main", description="d", method="git", file_count=0)

    await molt_store.delete_molt(db, "molt_d")
    count = await molt_store.count_molts(db, "s1")
    assert count == 0


def test_molt_dir_uses_workspace(tmp_path: Path):
    result = molt_store.molt_dir(tmp_path)
    assert result == tmp_path / ".crabagent" / "molts"


def test_snapshot_path_builds_correctly(tmp_path: Path):
    result = molt_store.snapshot_path("molt_001", "src/app.py", tmp_path)
    assert "molt_001" in str(result)
    assert "src/app.py" in str(result)


@pytest.mark.asyncio
async def test_list_molt_files_returns_empty_for_nonexistent(tmp_path: Path):
    result = await molt_store.list_molt_files("nonexistent", workspace=tmp_path)
    assert isinstance(result, list)


def test_get_snapshot_content_returns_empty_for_missing(tmp_path: Path):
    result = molt_store.get_snapshot_content("nonexistent", "file.py", workspace=tmp_path)
    assert result == ""


def test_get_current_content_returns_empty_for_missing(tmp_path: Path):
    result = molt_store.get_current_content(tmp_path, "nonexistent.py")
    assert result == ""


def test_get_current_content_reads_file(tmp_path: Path):
    f = tmp_path / "test.py"
    f.write_text("hello world")
    result = molt_store.get_current_content(tmp_path, "test.py")
    assert result == "hello world"

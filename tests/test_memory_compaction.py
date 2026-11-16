import json

import pytest
from sqlalchemy import func, select

from crabagent.core import database
from crabagent.core.memory_compaction import compact_memories


@pytest.mark.asyncio
async def test_compaction_archives_and_preserves_other_users(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(database.AgentMemory.__table__.create)
        await conn.run_sync(database.MemoryEmbedding.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async def semantic_ok(*args, **kwargs):
        return {"status": "ok", "merged": 0}
    monkeypatch.setattr("crabagent.core.memory_batch_merge.semantic_consolidate", semantic_ok)
    monkeypatch.setattr(database, "async_session_factory", sessions)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    async with sessions() as session:
        session.add_all([database.AgentMemory(user_id=1, key=f"k{i}", content=f"v{i}",
                        memory_type="team", importance=i / 10) for i in range(6)])
        session.add(database.AgentMemory(user_id=2, memory_type="team", key="other", content="other"))
        await session.commit()
        row = (await session.execute(select(database.AgentMemory).where(database.AgentMemory.key == "k0"))).scalar_one()
        session.add(database.MemoryEmbedding(memory_id=row.id, embedding="encoded", model_name="test"))
        await session.commit()
    assert await compact_memories(1, high_water=7, target=3) == 0
    assert await compact_memories(1, high_water=6, target=3) == 3
    async with sessions() as session:
        assert (await session.execute(select(func.count()).select_from(database.AgentMemory))).scalar_one() == 4
        assert (await session.execute(select(func.count()).select_from(database.MemoryEmbedding))).scalar_one() == 0
    path = next((tmp_path / ".crabagent" / "memory-archives").glob("*.json"))
    data = json.loads(path.read_text())
    assert len(data["memories"]) == 3
    assert len(data["embeddings"]) == 1
    assert path.stat().st_mode & 0o777 == 0o600
    await engine.dispose()


@pytest.mark.asyncio
async def test_restore_never_overwrites_existing_or_crosses_user(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from crabagent.core.memory_compaction import list_archives, restore_archived_memory

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'restore.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(database.AgentMemory.__table__.create)
        await conn.run_sync(database.MemoryEmbedding.__table__.create)
    async def semantic_ok(*args, **kwargs):
        return {"status": "ok", "merged": 0}
    monkeypatch.setattr("crabagent.core.memory_batch_merge.semantic_consolidate", semantic_ok)
    monkeypatch.setattr(database, "async_session_factory", async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    async with database.async_session_factory() as session:
        session.add_all([database.AgentMemory(user_id=1, memory_type="team", key=f"k{i}", content=f"v{i}")
                         for i in range(3)])
        await session.commit()
    assert await compact_memories(1, high_water=3, target=1) == 2
    archive = list_archives(1)[0]["name"]
    from crabagent.core.memory_compaction import read_archive
    record = read_archive(1, archive)["memories"][0]
    assert await restore_archived_memory(1, archive, record["id"]) == "restored"
    assert await restore_archived_memory(1, archive, record["id"]) == "exists"
    with pytest.raises(ValueError):
        await restore_archived_memory(2, archive, record["id"])
    with pytest.raises(ValueError):
        read_archive(1, "../secret.json")
    await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_archives_filter_by_owner(tmp_path, monkeypatch):
    from crabagent.core.memory_compaction import list_archives, read_archive

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    folder = tmp_path / ".crabagent"
    folder.mkdir()
    path = folder / "memory-archive-20261116-100625.json"
    path.write_text(json.dumps({"memories": [{"id": 1, "user_id": 1}, {"id": 2, "user_id": 2}]}))
    assert list_archives(1)[0]["count"] == 1
    assert list_archives(2)[0]["count"] == 1
    assert list_archives(3) == []
    assert read_archive(1, path.name)["memories"][0]["id"] == 1


@pytest.mark.asyncio
async def test_failed_archive_preserves_active_records(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fail.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(database.AgentMemory.__table__.create)
        await conn.run_sync(database.MemoryEmbedding.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async def semantic_ok(*args, **kwargs):
        return {"status": "ok", "merged": 0}
    monkeypatch.setattr("crabagent.core.memory_batch_merge.semantic_consolidate", semantic_ok)
    monkeypatch.setattr(database, "async_session_factory", sessions)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    async with sessions() as session:
        session.add_all([database.AgentMemory(user_id=1, memory_type="team", key=f"k{i}", content="v")
                         for i in range(3)])
        await session.commit()
    def fail(*args, **kwargs):
        raise OSError("disk failure")
    monkeypatch.setattr("crabagent.core.memory_compaction.os.fsync", fail)
    with pytest.raises(OSError):
        await compact_memories(1, high_water=3, target=1)
    async with sessions() as session:
        assert (await session.execute(select(func.count()).select_from(database.AgentMemory))).scalar_one() == 3
    await engine.dispose()

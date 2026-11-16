"""Regression tests for memory isolation and embedding invalidation."""

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core import database
from crabagent.serve.api.memory import list_memories


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(database.AgentMemory.__table__.create)
        await conn.run_sync(database.MemoryEmbedding.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "async_session_factory", sessions)

    async def no_embedding(*args):
        pass

    monkeypatch.setattr(database, "agent_memory_ensure_embedding", no_embedding)
    yield sessions
    await engine.dispose()


@pytest.mark.asyncio
async def test_scoped_upsert_and_search(db):
    for scope, workspace, agent, content in [
        ("global", "", "", "global"),
        ("workspace", "/a", "", "project a"),
        ("workspace", "/b", "", "project b"),
        ("agent", "/a", "coder", "coder a"),
        ("agent", "/a", "other", "other a"),
    ]:
        await database.agent_memory_upsert(1, "team", agent, "test", "same", content,
                                           scope=scope, workspace_path=workspace)
    rows = await database.agent_memory_search(1, "same", limit=20, visible_only=True,
                                              workspace_path="/a", agent_name="coder")
    assert {r["content"] for r in rows} == {"global", "project a", "coder a"}
    assert not await database.agent_memory_delete(1, "same")
    async with db() as session:
        assert len((await session.execute(select(database.AgentMemory))).scalars().all()) == 5


@pytest.mark.asyncio
async def test_embedding_invalidated_and_deleted(db):
    await database.agent_memory_upsert(1, "team", "", "test", "key", "old")
    async with db() as session:
        row = (await session.execute(select(database.AgentMemory))).scalar_one()
        session.add(database.MemoryEmbedding(memory_id=row.id, embedding="old", model_name="test"))
        await session.commit()
    assert await database.agent_memory_replace(1, "key", "old", "new")
    async with db() as session:
        assert (await session.execute(select(database.MemoryEmbedding))).scalars().all() == []
        session.add(database.MemoryEmbedding(memory_id=row.id, embedding="new", model_name="test"))
        await session.commit()
    assert await database.agent_memory_delete(1, "key")
    async with db() as session:
        assert (await session.execute(select(database.MemoryEmbedding))).scalars().all() == []


@pytest.mark.asyncio
async def test_management_search_before_limit(db):
    from types import SimpleNamespace

    async with db() as session:
        session.add_all([database.AgentMemory(user_id=1, memory_type="team", key="match", content="old"),
                         database.AgentMemory(user_id=1, memory_type="team", key="other", content="new")])
        await session.commit()
        result = await list_memories(memory_type="", category="", agent_name="", workspace="",
                                     scope="", recall_policy="", limit=1, q="match",
                                     user=SimpleNamespace(id=1), db=session)
        assert [row["key"] for row in result] == ["match"]


@pytest.mark.asyncio
async def test_concurrent_scoped_upsert(db):
    import asyncio

    await asyncio.gather(*(
        database.agent_memory_upsert(1, "team", "", "test", "same", str(i),
                                     scope="workspace", workspace_path="/a")
        for i in range(8)
    ))
    async with db() as session:
        rows = (await session.execute(select(database.AgentMemory))).scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_precise_delete_is_visibility_scoped(db):
    await database.agent_memory_upsert(1, "team", "", "test", "same", "a",
                                       scope="workspace", workspace_path="/a")
    await database.agent_memory_upsert(1, "team", "", "test", "same", "b",
                                       scope="workspace", workspace_path="/b")
    async with db() as session:
        rows = (await session.execute(select(database.AgentMemory))).scalars().all()
        ids = {row.content: row.id for row in rows}
    assert not await database.agent_memory_delete(1, "same", memory_id=ids["b"],
                                                   visible_only=True, workspace_path="/a")
    assert await database.agent_memory_delete(1, "same", memory_id=ids["a"],
                                              visible_only=True, workspace_path="/a")


@pytest.mark.asyncio
async def test_vector_recall_includes_unindexed_keyword_match(db, monkeypatch):
    import base64
    import struct

    from crabagent.core import memory_embed

    async def query_vector(_query):
        return [1.0, 0.0]

    monkeypatch.setattr(memory_embed, "encode_query", query_vector)
    await database.agent_memory_upsert(1, "team", "", "test", "indexed", "other")
    await database.agent_memory_upsert(1, "team", "", "test", "edited", "needle")
    async with db() as session:
        row = (await session.execute(select(database.AgentMemory).where(
            database.AgentMemory.key == "indexed"))).scalar_one()
        session.add(database.MemoryEmbedding(memory_id=row.id,
                    embedding=base64.b64encode(struct.pack("ff", 1.0, 0.0)).decode(),
                    model_name="test"))
        await session.commit()
    result = await database.agent_memory_search_vector(1, "needle", limit=2)
    assert "edited" in {item["key"] for item in result}


@pytest.mark.asyncio
async def test_vector_search_rebuilds_missing_embeddings(db, monkeypatch):
    from crabagent.core import memory_embed

    calls = []

    async def query_vector(_query):
        return [1.0, 0.0]

    async def rebuild(memory_id, key, content):
        calls.append((memory_id, key, content))

    monkeypatch.setattr(memory_embed, "encode_query", query_vector)
    monkeypatch.setattr(database, "agent_memory_ensure_embedding", rebuild)
    await database.agent_memory_upsert(1, "team", "", "test", "missing", "content")
    calls.clear()
    await database.agent_memory_search_vector(1, "content")
    assert len(calls) == 1
    assert calls[0][1:] == ("missing", "content")

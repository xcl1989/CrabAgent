import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core import database
from crabagent.core.memory_batch_merge import semantic_consolidate


@pytest.mark.asyncio
async def test_batch_merge_preserves_content_and_isolation(tmp_path, monkeypatch):
    from crabagent.core import memory_batch_merge as batch
    from crabagent.core import memory_embed, provider_store
    from crabagent.core.agent import reflect

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'batch.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(database.AgentMemory.__table__.create)
        await conn.run_sync(database.MemoryEmbedding.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "async_session_factory", sessions)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    async with sessions() as session:
        session.add_all(
            [
                database.AgentMemory(
                    user_id=1,
                    memory_type="team",
                    scope="workspace",
                    workspace_path="/a",
                    key="a",
                    content="Use cautious deployment steps.",
                    importance=0.8,
                ),
                database.AgentMemory(
                    user_id=1,
                    memory_type="team",
                    scope="workspace",
                    workspace_path="/a",
                    key="b",
                    content="Use cautious deployment steps and back up first.",
                    importance=0.9,
                ),
                database.AgentMemory(
                    user_id=1,
                    memory_type="team",
                    scope="workspace",
                    workspace_path="/b",
                    key="c",
                    content="Use cautious deployment steps.",
                    importance=0.8,
                ),
            ]
        )
        await session.commit()

    async def params(_):
        return {"api_key": "test"}

    async def provider(*args):
        return SimpleNamespace(provider_type="openai")

    async def vector(_):
        return [1.0]

    async def completion(**kwargs):
        pairs = json.loads(kwargs["messages"][1]["content"])
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({"merge_pairs": [[p["a"], p["b"]] for p in pairs]}) + "\nModel explanation"
                    )
                )
            ]
        )

    monkeypatch.setattr(reflect, "_resolve_llm_params", params)
    monkeypatch.setattr(provider_store, "get_default_provider", provider)
    monkeypatch.setattr(memory_embed, "encode_query", vector)
    monkeypatch.setattr(memory_embed, "cosine_similarity", lambda *_: 0.95)
    monkeypatch.setattr(batch.litellm, "acompletion", completion)
    result = await semantic_consolidate(1, model="openai/test")
    assert result["merged"] == 1
    async with sessions() as session:
        rows = (await session.execute(select(database.AgentMemory))).scalars().all()
        assert len(rows) == 2
        assert "back up first" in next(r.content for r in rows if r.workspace_path == "/a")
        assert next(r.content for r in rows if r.workspace_path == "/b") == "Use cautious deployment steps."
    archive = json.loads(next((tmp_path / ".crabagent" / "memory-archives").glob("*.json")).read_text())
    assert len(archive["memories"]) == 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_no_embeddings_recall_requires_separate_approval_and_isolation(tmp_path, monkeypatch):
    from crabagent.core import memory_batch_merge as batch
    from crabagent.core import memory_embed, provider_store
    from crabagent.core.agent import reflect

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'recall.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(database.AgentMemory.__table__.create)
        await conn.run_sync(database.MemoryEmbedding.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "async_session_factory", sessions)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    async with sessions() as session:
        session.add_all(
            [
                database.AgentMemory(
                    user_id=1,
                    memory_type="team",
                    scope="workspace",
                    workspace_path="/a",
                    key="a",
                    content="Deploy only after a backup.",
                ),
                database.AgentMemory(
                    user_id=1,
                    memory_type="team",
                    scope="workspace",
                    workspace_path="/a",
                    key="b",
                    content="Before releasing, make a copy of the data.",
                ),
                database.AgentMemory(
                    user_id=1,
                    memory_type="team",
                    scope="workspace",
                    workspace_path="/b",
                    key="c",
                    content="Deploy only after a backup.",
                ),
                database.AgentMemory(
                    user_id=2,
                    memory_type="team",
                    scope="workspace",
                    workspace_path="/a",
                    key="d",
                    content="Deploy only after a backup.",
                ),
            ]
        )
        await session.commit()

    async def params(_):
        return {"api_key": "test"}

    async def provider(*_):
        return SimpleNamespace(provider_type="openai")

    async def no_vector(_):
        return None

    calls = []

    async def completion(**kwargs):
        payload = json.loads(kwargs["messages"][1]["content"])
        calls.append(payload)
        key = "candidate_pairs" if len(calls) == 1 else "merge_pairs"
        pairs = [[p["a"], p["b"]] for p in payload] if len(calls) == 1 else []
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({key: pairs})))])

    monkeypatch.setattr(reflect, "_resolve_llm_params", params)
    monkeypatch.setattr(provider_store, "get_default_provider", provider)
    monkeypatch.setattr(memory_embed, "encode_query", no_vector)
    monkeypatch.setattr(batch.litellm, "acompletion", completion)
    result = await semantic_consolidate(1, model="openai/test")
    assert result["candidates"] == 1 and result["merged"] == 0
    assert len(calls) == 2 and len(calls[0]) == 1
    async with sessions() as session:
        assert len((await session.execute(select(database.AgentMemory))).scalars().all()) == 4
    await engine.dispose()


@pytest.mark.asyncio
async def test_recall_rejects_unknown_pairs_and_bounds_batches(monkeypatch):
    from crabagent.core import memory_batch_merge as batch

    items = [{"id": i, "identity": (1,), "content": str(i)} for i in range(42)]
    vectors = {i: None for i in range(42)}
    calls = []

    async def completion(**kwargs):
        payload = json.loads(kwargs["messages"][1]["content"])
        calls.append(payload)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"candidate_pairs": []}'))])

    monkeypatch.setattr(batch.litellm, "acompletion", completion)
    _, incomplete = await batch._recall_without_embeddings(items, vectors, "model", {}, lambda **_: None)
    assert incomplete and len(calls) == 40 and all(len(c) <= 20 for c in calls)

    async def invalid(**_):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"candidate_pairs": [[0, 999]]}'))]
        )

    monkeypatch.setattr(batch.litellm, "acompletion", invalid)
    with pytest.raises(ValueError):
        await batch._recall_without_embeddings(items, vectors, "model", {}, lambda **_: None)

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core import database
from crabagent.core.agent import memory_merge, reflect


@pytest.mark.asyncio
async def test_semantic_merge_scope_and_conflict(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'merge.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(database.AgentMemory.__table__.create)
        await conn.run_sync(database.MemoryEmbedding.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "async_session_factory", sessions)
    async with sessions() as db:
        db.add_all([
            database.AgentMemory(user_id=1, memory_type="user_preference", key="old", category="format",
                                 scope="global", workspace_path="", agent_name="", content="Use compact replies"),
            database.AgentMemory(user_id=2, memory_type="user_preference", key="other", category="format",
                                 scope="global", workspace_path="", agent_name="", content="Use compact replies"),
        ])
        await db.commit()
    async def params(_):
        return {"api_key": "test"}
    async def similar(*args):
        return 0.95
    async def response(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
            "merge": True, "content": "Use compact replies and include actionable next steps."})))])
    monkeypatch.setattr(reflect, "_resolve_llm_params", params)
    monkeypatch.setattr(memory_merge, "embedding_similarity_score", similar)
    monkeypatch.setattr(memory_merge.litellm, "acompletion", response)
    pref = {"category": "format", "content": "Keep responses brief and include next steps"}
    assert await memory_merge.merge_preference(1, pref, "test")
    async with sessions() as db:
        rows = (await db.execute(select(database.AgentMemory).order_by(database.AgentMemory.user_id))).scalars().all()
        assert "next steps" in rows[0].content
        assert rows[1].content == "Use compact replies"
    async def reject(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"merge":false}'))])
    monkeypatch.setattr(memory_merge.litellm, "acompletion", reject)
    assert not await memory_merge.merge_preference(1, pref, "test")
    await engine.dispose()

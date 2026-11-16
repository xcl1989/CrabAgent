"""Regression coverage for prompt injection against a real SQLite database."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core import database
from crabagent.core.agent.agents import build_memory_prompt


@pytest_asyncio.fixture
async def memory_db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(database.AgentMemory.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "async_session_factory", sessions)
    yield sessions
    await engine.dispose()


@pytest.mark.asyncio
async def test_prompt_filters_team_memories_and_preserves_legacy(memory_db):
    rows = [
        (1, "team", "global", "", "always", "global"),
        (1, "team", "workspace", "/project/a", "always", "project-a"),
        (1, "team", "workspace", "/project/b", "always", "project-b"),
        (1, "team", "", "", "", "legacy-global"),
        (1, "team", "", "/project/a", "", "legacy-a"),
        (1, "team", "", "/project/b", "", "legacy-b"),
        (1, "team", "global", "", "query_only", "query-only"),
        (1, "team", "agent", "/project/a", "always", "agent-only"),
        (2, "team", "global", "", "always", "other-user"),
        (1, "lesson", "global", "", "always", "other-type"),
    ]
    async with memory_db() as session:
        for user, kind, scope, workspace, policy, key in rows:
            session.add(database.AgentMemory(
                user_id=user, memory_type=kind, key=key, content=key,
                scope=scope, workspace_path=workspace, recall_policy=policy,
            ))
        await session.commit()

    prompt = await build_memory_prompt(1, workspace_path="/project/a")
    for key in ("global", "project-a", "legacy-global", "legacy-a"):
        assert f"**{key}**" in prompt
    for key in ("project-b", "legacy-b", "query-only", "agent-only", "other-user", "other-type"):
        assert f"**{key}**" not in prompt

    no_workspace = await build_memory_prompt(1)
    assert "**legacy-global**" in no_workspace
    assert "**legacy-a**" not in no_workspace
    assert await database.agent_memory_get_by_type(1, "team", scope="workspace") == []
    # Existing callers with no new filters retain the original behavior.
    assert len(await database.agent_memory_get_by_type(1, "team")) == 8


@pytest.mark.asyncio
async def test_filtering_happens_before_limit(memory_db):
    async with memory_db() as session:
        for i in range(10):
            session.add(database.AgentMemory(user_id=1, memory_type="team", key=f"wrong-{i}",
                scope="workspace", workspace_path="/elsewhere", recall_policy="always", importance=1.0))
        session.add(database.AgentMemory(user_id=1, memory_type="team", key="wanted",
            content="included", scope="global", recall_policy="always", importance=0.1))
        await session.commit()
    assert "included" in await build_memory_prompt(1, workspace_path="/project/a")

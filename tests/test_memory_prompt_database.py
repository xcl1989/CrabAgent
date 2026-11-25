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
async def test_get_by_type_filters_scope_and_policy(memory_db):
    """``agent_memory_get_by_type`` still filters by scope and recall policy;
    callers other than the prompt builder rely on it (memory page, recall)."""
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

    visible = await database.agent_memory_get_by_type(
        1, "team", scope="workspace", workspace_path="/project/a", recall_policy="always"
    )
    # Legacy rows (blank policy) are treated as "always" by this helper so old
    # data keeps working; they are still inert in injection (see test below).
    assert [m["key"] for m in visible] == ["project-a", "legacy-a"]
    # No policy filter → legacy (blank) rows are included, as before.
    assert len(await database.agent_memory_get_by_type(1, "team")) == 8


@pytest.mark.asyncio
async def test_prompt_has_no_unconditional_team_block(memory_db, monkeypatch):
    """``recall_policy="always"`` must not put anything into the system prompt.

    The old ``build_memory_prompt`` prepended a "Team Knowledge" block on every
    CLI turn; that block was removed. Only the save instruction and
    query-relevant memories remain.
    """
    from crabagent.core.config import settings

    monkeypatch.setattr(settings, "memory_auto_recall", False)
    async with memory_db() as session:
        for i in range(10):
            session.add(database.AgentMemory(user_id=1, memory_type="team", key=f"rule-{i}",
                content=f"rule body {i}", scope="global", recall_policy="always", importance=1.0 - i * 0.01))
        await session.commit()
    prompt = await build_memory_prompt(1, workspace_path="/project/a")
    assert "**rule-" not in prompt
    assert "memory_save" in prompt  # the save instruction is still there

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core.conversations import history
from crabagent.core.database import Base, Conversation, Message


@pytest.fixture
async def history_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'history.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(history, "async_session_factory", factory)
    async with factory() as db:
        visible = Conversation(
            session_id="visible", user_id=1, title="Roadmap", workspace="/project-a", active_branch="main"
        )
        private = Conversation(
            session_id="private", user_id=1, title="Secret roadmap", workspace="/project-b", history_searchable=False
        )
        other_user = Conversation(session_id="other", user_id=2, title="Roadmap", workspace="/project-c")
        db.add_all([visible, private, other_user])
        await db.flush()
        db.add_all(
            [
                Message(conversation_id=visible.id, sequence=1, role="user", content="Discuss the roadmap"),
                Message(conversation_id=visible.id, sequence=2, role="assistant", content="Implement history search"),
                Message(conversation_id=visible.id, sequence=3, role="tool", content="sensitive tool output"),
                Message(
                    conversation_id=visible.id,
                    sequence=4,
                    role="assistant",
                    content="Feature branch",
                    branch_id="feature",
                ),
                Message(conversation_id=private.id, sequence=1, role="assistant", content="Secret roadmap details"),
                Message(conversation_id=other_user.id, sequence=1, role="assistant", content="Other user roadmap"),
            ]
        )
        await db.commit()
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_search_history_enforces_user_workspace_and_session_visibility(history_db):
    results = await history.search_history(user_id=1, query="roadmap")
    assert [item.session_id for item in results] == ["visible"]

    filtered = await history.search_history(user_id=1, query="roadmap", workspace="/project-b")
    assert filtered == []

    excluded = await history.search_history(user_id=1, query="roadmap", exclude_session_id="visible")
    assert excluded == []


@pytest.mark.asyncio
async def test_read_history_filters_internal_messages_and_selects_branch(history_db):
    main = await history.read_history(user_id=1, session_id="visible", max_messages=10)
    assert main is not None
    assert [message.role for message in main.messages] == ["user", "assistant"]
    assert all("sensitive" not in message.content for message in main.messages)

    feature = await history.read_history(user_id=1, session_id="visible", branch_id="feature")
    assert feature is not None
    assert [message.content for message in feature.messages] == ["Feature branch"]

    assert await history.read_history(user_id=1, session_id="private") is None
    assert await history.read_history(user_id=1, session_id="other") is None

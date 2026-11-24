import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def sessions(tmp_path, monkeypatch):
    """Isolated SQLite database with the session-memory schema applied."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from crabagent.core import database
    from crabagent.core.agent import loop
    from crabagent.core.agent import session_memory as sm

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(database.Base.metadata.create_all)
        await database._migrate_session_memory(conn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(sm, "async_session_factory", factory)
    monkeypatch.setattr(loop.settings, "memory_auto_recall", True)
    monkeypatch.setattr(loop.settings, "session_memory_models", ["test:openai/gpt-4o"])
    async with factory.begin() as db:
        db.add(database.Conversation(id=1, session_id="s", user_id=7, workspace=str(tmp_path)))
        for i in range(1, 5):
            db.add(database.Message(id=i, conversation_id=1, sequence=i, branch_id="main", role="user"))
    yield factory
    await engine.dispose()

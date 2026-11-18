import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core.collaboration.auto_binding import ensure_session_binding
from crabagent.core.database import Base, CollaborationBinding, CollaborationEntry, CollaborationProject, Conversation


@pytest.mark.asyncio
async def test_auto_binding_concurrent_and_isolated(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    workspace = tmp_path / "project"
    workspace.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(workspace, target_is_directory=True)
    async with factory() as db:
        db.add_all(
            [
                Conversation(session_id="a", user_id=1, workspace=str(alias)),
                Conversation(session_id="b", user_id=1, workspace=str(workspace)),
                Conversation(session_id="c", user_id=2, workspace=str(workspace)),
            ]
        )
        await db.commit()

    async def bind(user, session):
        async with factory() as db:
            return await ensure_session_binding(db, user, session)

    a, b, c = await asyncio.gather(bind(1, "a"), bind(1, "b"), bind(2, "c"))
    assert a == b and c != a
    assert await bind(2, "a") is None
    async with factory() as db:
        projects = (await db.execute(select(CollaborationProject))).scalars().all()
        assert len(projects) == 2
        assert all(p.workspace == str(workspace.resolve()) for p in projects)
    await engine.dispose()


@pytest.mark.asyncio
async def test_workspace_change_and_invalid_workspace_close_only_own_claims(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    async with factory() as db:
        db.add(Conversation(session_id="a", user_id=1, workspace=str(first)))
        await db.commit()
    async with factory() as db:
        old = await ensure_session_binding(db, 1, "a")
    async with factory() as db:
        db.add_all(
            [
                CollaborationEntry(user_id=1, project_id=old, session_id="a", kind="claim", content="mine"),
                CollaborationEntry(user_id=1, project_id=old, session_id="b", kind="claim", content="other"),
                CollaborationEntry(user_id=1, project_id=old, session_id="a", kind="handoff", content="note"),
            ]
        )
        conv = (await db.execute(select(Conversation))).scalar_one()
        conv.workspace = str(second)
        await db.commit()
    async with factory() as db:
        new = await ensure_session_binding(db, 1, "a")
        assert new != old
    async with factory() as db:
        entries = (await db.execute(select(CollaborationEntry).order_by(CollaborationEntry.id))).scalars().all()
        assert [e.state for e in entries] == ["closed", "active", "active"]
        conv = (await db.execute(select(Conversation))).scalar_one()
        conv.workspace = ""
        await db.commit()
    async with factory() as db:
        assert await ensure_session_binding(db, 1, "a") is None
        assert await db.get(CollaborationBinding, "a") is None
    async with factory() as db:
        conv = (await db.execute(select(Conversation))).scalar_one()
        conv.workspace = str(tmp_path / "missing")
        await db.commit()
    async with factory() as db:
        assert await ensure_session_binding(db, 1, "a") is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_read_only_binding_fast_path_and_persistent_unbind(tmp_path):
    from types import SimpleNamespace

    from sqlalchemy import text

    from crabagent.serve.api.collaboration import BindingRequest, unbind_session

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", connect_args={"timeout": 0.1})
    try:
        async with engine.begin() as conn:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            db.add_all([Conversation(session_id="bound", user_id=1, workspace=str(tmp_path)),
                        Conversation(session_id="ordinary", user_id=1, workspace="")])
            await db.commit()
            project_id = await ensure_session_binding(db, 1, "bound")
        async with factory() as writer:
            await writer.execute(text("BEGIN IMMEDIATE"))
            async with factory() as db:
                assert await ensure_session_binding(db, 1, "ordinary") is None
                assert await ensure_session_binding(db, 1, "bound") == project_id
            await writer.rollback()
        async with factory() as db:
            await unbind_session(project_id, BindingRequest(session_id="bound"), user=SimpleNamespace(id=1), db=db)
            assert await ensure_session_binding(db, 1, "bound") is None
            assert await db.get(CollaborationBinding, "bound") is None
    finally:
        await engine.dispose()

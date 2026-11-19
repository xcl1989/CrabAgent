from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core import database as dbm
from crabagent.core.agent import session_memory as sm
from crabagent.serve.api.branch import BranchRequest, create_branch


@pytest.mark.parametrize("target_id, expected_count", [(3, 2), (4, 4)])
async def test_branch_inherits_only_admitted_ancestor_snapshots(tmp_path, monkeypatch, target_id, expected_count):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'branch.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(sm, "async_session_factory", sessions)
    user = SimpleNamespace(id=7)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(dbm.Base.metadata.create_all)
            await dbm._migrate_session_memory(conn)
        async with sessions.begin() as db:
            db.add(dbm.Conversation(id=1, session_id="s", user_id=user.id, workspace=str(tmp_path)))
            db.add_all([
                dbm.Message(id=1, conversation_id=1, sequence=1, role="user", compressed=True, agent="coder"),
                dbm.Message(id=2, conversation_id=1, sequence=2, role="user", agent="coder"),
                dbm.Message(id=3, conversation_id=1, sequence=3, role="user", agent="coder"),
                dbm.Message(id=4, conversation_id=1, sequence=4, role="assistant", agent="coder"),
                dbm.Message(id=5, conversation_id=1, sequence=4, role="user", agent="coder"),
            ])
            source = sm.Source(user_id=user.id, memory_type="team", key="alpha", content="reference")
            db.add(source)
            await db.flush()
            uid = source.memory_uid
            for anchor_id in (1, 2, 3, 5):
                admitted = anchor_id != 3
                db.add(sm.Anchor(conversation_id=1, branch_id="main", anchor_message_id=anchor_id,
                                 first_admission_recorded=admitted))
                db.add(sm.Snapshot(conversation_id=1, branch_id="main", anchor_message_id=anchor_id,
                                   memory_uid=uid, content_revision=1, visibility_epoch=1, ordinal=0,
                                   snapshot_payload="reference", admitted=admitted))
        async with sessions() as db:
            result = await create_branch("s", BranchRequest(message_id=target_id, name="fork"), user, db)
            assert result["copied_messages"] == expected_count
            messages = (await db.scalars(select(dbm.Message).where(dbm.Message.branch_id == "fork")
                                         .order_by(dbm.Message.sequence))).all()
            assert messages[0].compressed is True
            assert all(msg.agent == "coder" and msg.id > 5 for msg in messages)
            if target_id == 4:
                batch = await db.get(sm.Anchor, (1, "fork", messages[2].id))
                assert batch and batch.first_admission_recorded
                assert not await db.get(sm.Snapshot, (1, "fork", messages[2].id, uid))
            ids = {msg.id for msg in messages if msg.role == "user"}
            visible_id = messages[1].id
            with pytest.raises(HTTPException) as error:
                await create_branch("s", BranchRequest(message_id=target_id, name="invalid"), user, db)
            assert error.value.status_code == 404
            await db.rollback()
        memory = sm.SessionMemory(user.id, 1, "fork", str(tmp_path))

        async def send(blocks):
            return blocks

        retry = sm.Admission()
        assert await memory.complete(ids, "coder", retry, dict, send) == {visible_id: ["reference"]}
        async with sessions.begin() as db:
            await db.execute(delete(sm.Source).where(sm.Source.memory_uid == uid))
        assert await memory.complete(ids, "coder", retry, dict, send) == {}
        async with sessions() as db:
            assert not (await db.scalars(select(sm.Snapshot))).all()
    finally:
        await engine.dispose()

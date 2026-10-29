from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core.database import Base, Conversation, Message
from crabagent.core.wechat import compaction, message, selection


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["success", "empty", "failure", "messages_changed", "selection_changed"])
async def test_transactional_compaction(tmp_path, monkeypatch, scenario):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(compaction, "async_session_factory", factory)
    monkeypatch.setattr(selection, "async_session_factory", factory)
    async with factory() as db:
        conv = Conversation(session_id="session", user_id=1, title="identity", workspace="/w", source="wechat")
        db.add(conv)
        await db.flush()
        cid = conv.id
        db.add_all(
            [
                Message(conversation_id=cid, branch_id="main", sequence=i, role="user", content=f"message {i}")
                for i in range(1, 4)
            ]
        )
        await db.commit()
    state = {"workspace": "/w", "sessions": {"/w": cid}, "model": "m", "provider": "p"}
    await selection.save("bot", "alice", state)

    async def summarize(history, model, provider):
        assert (model, provider) == ("m", "p")
        assert len(history) == 3
        if scenario == "failure":
            raise RuntimeError("provider failure")
        if scenario == "messages_changed":
            async with factory() as db:
                db.add(Message(conversation_id=cid, branch_id="main", sequence=4, role="user", content="new"))
                await db.commit()
        if scenario == "selection_changed":
            await selection.save("bot", "alice", {**state, "sessions": {"/w": 999}})
        return "" if scenario == "empty" else "summary"

    monkeypatch.setattr(message, "_summarize_conversation", AsyncMock(side_effect=summarize))
    result = await compaction.compact("bot", "alice", "/w", cid, "identity", "m", "p", threshold=2)
    assert result == (scenario == "success")
    async with factory() as db:
        rows = list((await db.scalars(select(Message).order_by(Message.sequence))).all())
        if result:
            assert all(r.compressed for r in rows[:3])
            assert (rows[-1].role, rows[-1].content, rows[-1].compressed) == ("compress", "summary", False)
            assert (await selection.load("bot", "alice"))["sessions"]["/w"] == cid
        else:
            assert all(not r.compressed for r in rows)
            assert not any(r.role == "compress" for r in rows)
    await engine.dispose()

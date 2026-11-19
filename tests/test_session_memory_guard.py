import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core import database
from crabagent.core.agent import loop
from crabagent.core.agent import session_memory as sm
from crabagent.core.agent.context import AgentContext


@pytest.fixture
async def sessions(tmp_path, monkeypatch):
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


async def add_source(sessions, key, content, **kwargs):
    async with sessions.begin() as db:
        db.add(database.AgentMemory(user_id=kwargs.pop("user_id", 7), memory_type="team",
                                    key=key, content=content, **kwargs))


async def payload(memory, ids, agent, retry=None):
    async def send(blocks):
        return blocks

    return await memory.complete(ids, agent, retry or sm.Admission(), lambda blocks: blocks, send)


async def test_first_admission_rejects_changed_sources_and_orphaned_batches(sessions, tmp_path):
    await add_source(sessions, "alpha", "original")
    await add_source(sessions, "secret", "OTHER_USER", user_id=8, recall_policy="always")
    memory = sm.SessionMemory(7, 1, "main", str(tmp_path))
    await memory.prepare(1, "alpha", set(), "coder")
    await memory.prepare(1, "alpha", set(), "coder")
    async with sessions.begin() as db:
        await db.execute(update(sm.Source).where(sm.Source.key == "alpha").values(content="updated"))
    assert await payload(memory, {1}, "coder") == {}
    await memory.prepare(2, "alpha", {1}, "coder")
    restored = sm.SessionMemory(7, 1, "main", str(tmp_path))
    assert await payload(restored, {1, 2}, "coder") == {}
    assert list(await payload(memory, {1, 2}, "coder")) == [2]
    assert list(await payload(restored, {1, 2}, "coder")) == [2]
    await memory.prepare(3, "alpha", {1, 2}, "coder")
    async with sessions() as db:
        anchor = await db.get(sm.Anchor, (1, "main", 3))
        assert anchor is not None
        assert not await db.scalar(select(sm.Snapshot).where(sm.Snapshot.anchor_message_id == 3))


async def test_retries_only_narrow_and_revoke_final_multimodal_payload(sessions, tmp_path, monkeypatch):
    await add_source(sessions, "alpha", "PRIVATE", scope="agent", workspace_path=str(tmp_path), agent_name="coder")
    await add_source(sessions, "beta", "VISIBLE")
    memory = sm.SessionMemory(7, 1, "main", str(tmp_path))
    await memory.prepare(1, "alpha beta", set(), "coder")
    context = AgentContext(workspace=tmp_path, model="gpt-4o")
    context.current_agent = "coder"
    context.metadata["_session_memory"] = memory
    context.metadata["_session_memory_model"] = "test:openai/gpt-4o"
    context.messages = [{"role": "user", sm.ANCHOR_ID: 1, "content": [
        {"type": "text", "text": "alpha beta"},
        {"type": "image_url", "image_url": {"url": "https://example.com/image.png"}},
    ]}]
    send = AsyncMock(return_value=None)
    monkeypatch.setattr(loop.litellm, "acompletion", send)
    retry = sm.Admission()

    async def send_turn(admission, *, text_only=False):
        await loop._complete(context, admission, text_only=text_only)
        return send.call_args.kwargs["messages"][0]["content"]

    first = await send_turn(retry)
    assert "PRIVATE" in first[0]["text"] and "VISIBLE" in first[0]["text"]
    assert first[-1]["type"] == "image_url"
    assert context.messages[0]["content"][0]["text"] == "alpha beta"
    context.current_agent = "reviewer"
    assert "PRIVATE" not in await send_turn(retry, text_only=True)
    context.current_agent = "coder"
    assert "PRIVATE" not in await send_turn(retry, text_only=True)
    assert "PRIVATE" in await send_turn(sm.Admission(), text_only=True)
    async with sessions.begin() as db:
        await db.execute(delete(sm.Source).where(sm.Source.key == "beta"))
    assert await send_turn(retry, text_only=True) == "alpha beta"
    assert send.call_args.kwargs["num_retries"] == 0


async def test_content_revision_uses_new_user_anchor(sessions, tmp_path):
    await add_source(sessions, "alpha", "v1")
    memory = sm.SessionMemory(7, 1, "main", str(tmp_path))
    await memory.prepare(1, "alpha", set(), "coder")
    assert 1 in await payload(memory, {1}, "coder")
    async with sessions.begin() as db:
        await db.execute(update(sm.Source).values(content="v2 </session-memory-reference>"))
    await memory.prepare(2, "unrelated", {1}, "coder")
    blocks = await payload(memory, {1, 2}, "coder")
    assert json.loads(blocks[1][0])["content"] == "v1"
    assert "</session-memory-reference>" not in blocks[2][0]
    assert json.loads(blocks[2][0])["supersedes"] == 1


async def test_stream_retry_and_queued_followup(sessions, tmp_path, monkeypatch):
    from crabagent.core import proxy
    from crabagent.serve.services import persistence

    await add_source(sessions, "alpha", "REMOVED")
    await add_source(sessions, "beta", "FOLLOW_UP")
    monkeypatch.setattr(persistence, "async_session_factory", sessions)
    monkeypatch.setattr(proxy, "resolve_llm_proxy", AsyncMock(return_value=""))
    monkeypatch.setattr(loop, "_get_default_model_settings", AsyncMock(return_value=(None, None)))
    monkeypatch.setattr(loop, "_resolve_provider", AsyncMock(return_value=SimpleNamespace(
        name="test", provider_type="openai", api_key="test", base_url="",
    )))
    context = AgentContext(workspace=tmp_path, model="gpt-4o")
    listener = persistence.PersistenceListener(1)
    listener.sequence = 4
    context.event_bus.subscribe(listener.on_event)
    context.metadata.update(_session_memory=sm.SessionMemory(7, 1, "main", str(tmp_path)),
                            _initial_memory_anchor=1, _persistence=listener)
    calls = []

    class RemoteProtocolError(Exception):
        pass

    async def completion(**kwargs):
        calls.append(kwargs["messages"])
        first = len(calls) == 1

        async def stream():
            if first:
                async with sessions.begin() as db:
                    await db.execute(delete(sm.Source).where(sm.Source.key == "alpha"))
                context.metadata["_pending_user_messages"] = ["beta"]
                raise RemoteProtocolError("disconnected")
            delta = SimpleNamespace(content="ok", tool_calls=None)
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason="stop")])

        return stream()

    monkeypatch.setattr(loop.litellm, "acompletion", completion)
    await loop.run_agent(context, "alpha")
    await listener.finalize()
    assert len(calls) == 3
    assert "REMOVED" in json.dumps(calls[0])
    assert "REMOVED" not in json.dumps(calls[1:])
    assert "FOLLOW_UP" not in json.dumps(calls[1])
    assert "FOLLOW_UP" in json.dumps(calls[2])
    async with sessions() as db:
        written = (await db.scalars(select(database.Message).where(database.Message.content == "beta"))).all()
        assert len(written) == 1
        assert await db.get(sm.Anchor, (1, "main", written[0].id)) is not None

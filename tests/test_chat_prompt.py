from types import SimpleNamespace
from unittest.mock import AsyncMock

import litellm
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core import proxy
from crabagent.core.agent import compress, loop
from crabagent.core.database import Conversation, Message
from crabagent.core.provider_store import ProviderInfo
from crabagent.serve.api import session
from crabagent.serve.services import chat_prompt, persistence


async def test_manual_summary_rebuilds_legacy_system_prompt(tmp_path, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    legacy_text = "STALE_AUTOMATIC_MEMORY_SENTINEL"
    (tmp_path / "AGENTS.md").write_text("Keep workspace rules.")
    monkeypatch.setattr(chat_prompt, "async_session_factory", sessions)
    monkeypatch.setattr(persistence, "async_session_factory", sessions)
    monkeypatch.setattr(chat_prompt, "build_team_prompt", AsyncMock(return_value=""))
    monkeypatch.setattr(compress.settings, "memory_auto_recall", False)
    monkeypatch.setattr(compress.settings, "context_keep_recent", 2)
    monkeypatch.setattr(proxy, "resolve_llm_proxy", AsyncMock(return_value=""))
    monkeypatch.setattr(
        loop, "_resolve_provider",
        AsyncMock(return_value=ProviderInfo("test", "Test", "openai", "test", "", True, True, {})),
    )
    captured = []

    async def fake_completion(**kwargs):
        captured.extend(kwargs["messages"])

        async def stream():
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="A summary"))])

        return stream()

    monkeypatch.setattr(litellm, "acompletion", fake_completion)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Conversation.__table__.create)
            await conn.run_sync(Message.__table__.create)
        async with sessions() as db:
            conv = Conversation(
                session_id="legacy", user_id=1, workspace=str(tmp_path), system_prompt=legacy_text, prompt_locale="en",
            )
            db.add(conv)
            await db.flush()
            db.add_all([
                Message(conversation_id=conv.id, sequence=i, role="user", content=f"Original turn {i}")
                for i in range(6)
            ])
            await db.commit()
            result = await session.compress_session(
                "legacy", session.CompressSessionRequest(), SimpleNamespace(id=1, locale="en"), db,
            )
            await db.refresh(conv)
            assert conv.prompt_schema_version == chat_prompt.CHAT_PROMPT_SCHEMA_VERSION
            assert await chat_prompt.get_chat_base_prompt(conv, tmp_path, "en") == captured[0]["content"]
    finally:
        await engine.dispose()

    assert result.summary == "A summary"
    assert captured[0]["role"] == "system"
    assert "Keep workspace rules." in captured[0]["content"]
    assert "Original turn 0" in [message["content"] for message in captured]
    assert all(legacy_text not in message["content"] for message in captured)

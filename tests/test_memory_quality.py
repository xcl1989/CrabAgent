from datetime import datetime

import pytest
from sqlalchemy import func, select

from crabagent.core import database, memory_quality
from crabagent.core.agent import session_memory as sm
from crabagent.core.memory_quality import build_report, classify_preference, has_random_suffix


@pytest.fixture
async def sessions(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'q.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(database.Base.metadata.create_all)
        await database._migrate_session_memory(conn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(sm, "async_session_factory", factory)
    monkeypatch.setattr(memory_quality, "async_session_factory", factory)
    yield factory
    await engine.dispose()


async def add(factory, **kwargs):
    kwargs.setdefault("user_id", 7)
    async with factory.begin() as db:
        db.add(database.AgentMemory(created_at=datetime(2026, 11, 24), **kwargs))


def test_classifiers():
    assert classify_preference("When the assistant reports completion, the user asks for curl") == "assistant_behaviour"
    assert classify_preference("助手应自动验证打包产物") == "assistant_behaviour"
    assert classify_preference("The model needs to verify the packaged app") == "assistant_behaviour"
    # "When the user says X, do Y" may be a habit or a one-off: surface it,
    # but do not call it assistant behaviour.
    assert classify_preference("When the user says 直接删除, execute it immediately") == "conditional_rule"
    assert classify_preference(
        "When a newly built application fails to launch, check the signing log",
    ) == "conditional_rule"
    assert classify_preference("User prefers Chinese for chat, English for code.") is None
    assert classify_preference("Prefers simple, unified architectures") is None
    assert classify_preference("用户期望不同记忆类别保持边界") is None
    assert has_random_suffix("user_pref:doc-sync:f6a5eca42734")
    assert not has_random_suffix("user_pref:workflow:verify-build")


@pytest.mark.parametrize("assistant_prefix", ["When the assistant mischaracterizes a blocker, the user corrects it",
                                              "助手应自动验证打包产物并测量缓存"])
async def test_report_flags_behaviour_random_keys_and_overflow(sessions, assistant_prefix):
    await add(sessions, memory_type="user_preference", key="user_pref:verify:cec7df35efed",
              category="general", content=assistant_prefix, importance=0.7)
    await add(sessions, memory_type="user_preference", key="user_pref:verify:aaaaaaaaaaaa",
              category="general", content=assistant_prefix + " with more detail", importance=0.7)
    await add(sessions, memory_type="user_preference", key="user_pref:language",
              category="language", content="User prefers Chinese for chat.", importance=0.6)
    await add(sessions, memory_type="user_preference", key="user_pref:lang:0123456789ab",
              category="language", content="User prefers Chinese for chat, English for code.", importance=0.6)
    for i in range(45):
        await add(sessions, memory_type="agent_lesson", key=f"lesson:coder:{i}", agent_name="coder",
                  category="effective_strategy", content=f"lesson {i}", importance=0.5 - i * 0.001)
    await add(sessions, memory_type="agent_lesson", key="lesson:researcher:1", agent_name="researcher",
              category="code", content="ok", importance=0.8)

    report = await build_report(7)
    s = report["summary"]
    assert s["preferences_flagged"] == 3
    assert s["assistant_behaviour"] == 2
    assert s["random_key"] == 3
    assert s["likely_duplicates"] == 2  # the behaviour pair; language pair is similar but not a duplicate
    assert s["lesson_overflow"] == 5
    keys = {f["key"]: f for f in report["preferences"]}
    assert "user_pref:language" not in keys  # clean key + clean content: nothing to flag
    assert keys["user_pref:verify:cec7df35efed"]["nearest"]["key"] == "user_pref:verify:aaaaaaaaaaaa"
    assert keys["user_pref:verify:cec7df35efed"]["nearest"]["duplicate"] is True
    assert keys["user_pref:lang:0123456789ab"]["issues"] == ["random_key"]
    assert keys["user_pref:lang:0123456789ab"]["nearest"] == {
        "key": "user_pref:language", "similarity": 0.77, "duplicate": False,
    }
    assert {f["agent_name"] for f in report["lessons"]} == {"coder"}
    assert all(f["issues"] == ["lesson_overflow"] for f in report["lessons"])
    # read-only: nothing changed
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(database.AgentMemory)) == 50


async def test_report_is_scoped_to_user(sessions):
    await add(sessions, memory_type="user_preference", key="user_pref:x:abcdefabcdef",
              category="general", content="When the assistant does X", importance=0.5)
    await add(sessions, memory_type="user_preference", key="user_pref:y:ffffffffff", user_id=8,
              category="general", content="When the assistant does Y", importance=0.5)
    report = await build_report(7)
    assert [f["key"] for f in report["preferences"]] == ["user_pref:x:abcdefabcdef"]


async def test_evidence_change_bumps_content_revision(sessions):
    await add(sessions, memory_type="user_preference", key="user_pref:z", category="language",
              content="User prefers terse answers.", evidence="quote A")
    async with sessions.begin() as db:
        row = await db.scalar(select(database.AgentMemory).where(database.AgentMemory.key == "user_pref:z"))
        assert row.content_revision == 1
        row.evidence = "quote B"
    async with sessions() as db:
        row = await db.scalar(select(database.AgentMemory).where(database.AgentMemory.key == "user_pref:z"))
        assert row.content_revision == 2

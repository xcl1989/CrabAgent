"""P1 extraction gate: closed vocabulary, evidence requirement, stable keys."""

import pytest

from crabagent.core.agent import preference_schema as ps

BASE = {
    "kind": "standing_rule",
    "category": "language",
    "slug": "chat-language",
    "content": "用中文回复，代码注释保持原文。",
    "evidence": "请使用简体中文回复",
}
USER_TURNS = ["你好，请看下这个 bug", "请使用简体中文回复，注释保持原文"]


def test_accepts_complete_candidate_and_derives_importance():
    cleaned, reason = ps.validate(BASE, USER_TURNS)
    assert reason == "ok"
    assert cleaned["key"] == "user_pref:chat-language"
    assert cleaned["importance"] == 0.8  # standing_rule


@pytest.mark.parametrize("kind,expected", [
    ("standing_rule", 0.8), ("correction", 0.7), ("explicit_choice", 0.6), ("repeated_request", 0.6),
])
def test_importance_comes_from_kind_not_the_model(kind, expected):
    cleaned, _ = ps.validate({**BASE, "kind": kind}, USER_TURNS)
    assert cleaned["importance"] == expected


@pytest.mark.parametrize("kind", ps.REJECTED_KINDS)
def test_rejects_assistant_behaviour_and_one_off_instructions(kind):
    cleaned, reason = ps.validate({**BASE, "kind": kind}, USER_TURNS)
    assert cleaned is None
    assert reason == f"rejected_kind:{kind}"


def test_rejects_unquotable_evidence():
    """The core guard: a candidate must quote the user, character for character."""
    cleaned, reason = ps.validate(
        {**BASE, "evidence": "After a restart the assistant should verify the app"}, USER_TURNS,
    )
    assert cleaned is None
    assert reason == "evidence_not_verbatim"


def test_rejects_unknown_category_and_bad_slug():
    cleaned, reason = ps.validate({**BASE, "category": "disk-cleanup"}, USER_TURNS)
    assert cleaned is None and reason.startswith("unknown_category")
    # normalize_slug is deliberately lenient; only a slug that stays unusable
    # after normalization (too short) is rejected.
    cleaned, reason = ps.validate({**BASE, "slug": "!!"}, USER_TURNS)
    assert cleaned is None and reason.startswith("bad_slug")


@pytest.mark.parametrize("evidence", ["", "  "])
def test_rejects_missing_evidence(evidence):
    cleaned, reason = ps.validate({**BASE, "evidence": evidence}, USER_TURNS)
    assert cleaned is None
    assert reason == "no_evidence"


def test_same_subject_maps_to_same_key():
    """Stable keys are what stop the hash-suffix explosion."""
    a, _ = ps.validate(BASE, USER_TURNS)
    b, _ = ps.validate({**BASE, "content": "用户希望全程中文，代码保持英文。"}, USER_TURNS)
    assert a["key"] == b["key"] == "user_pref:chat-language"


def test_normalize_slug_collapses_noise():
    assert ps.normalize_slug("Verify Build BEFORE install!") == "verify-build-before-install"
    assert ps.normalize_slug("  --x--  ") == "x"
    assert len(ps.normalize_slug("a" * 100)) <= ps.MAX_SLUG_CHARS


def test_parse_blocks_accepts_english_and_chinese_labels():
    text = (
        "Kind: correction\nCategory: workflow\nSlug: repeat-command\n"
        "Preference: 用户重复同一命令时要重新执行整个流程。\nEvidence: 重新执行\n\n"
        "类型: standing_rule\n类别: language\n主题: chat-language\n"
        "偏好: 用中文回复。\n依据: 用中文\n"
    )
    blocks = ps.parse_blocks(text)
    assert [b["kind"] for b in blocks] == ["correction", "standing_rule"]
    assert blocks[1]["category"] == "language"
    assert blocks[0]["slug"] == "repeat-command"


def test_parse_blocks_ignores_preference_without_content():
    assert ps.parse_blocks("Kind: correction\nCategory: workflow\n") == []


async def test_extractor_drops_candidates_without_user_quote(monkeypatch):
    """End-to-end through the extractor: the LLM's own words cannot pass as evidence."""
    from types import SimpleNamespace

    import crabagent.core.agent.reflect as reflect
    from crabagent.core.config import settings

    answer = (
        "Kind: assistant_behaviour\nCategory: workflow\nSlug: post-restart\n"
        "Preference: After packaging, verify the running build.\nEvidence: 我打包重启了\n\n"
        "Kind: single_instruction\nCategory: safety\nSlug: delete-now\n"
        "Preference: Delete data immediately without checks.\nEvidence: 直接删除\n\n"
        "Kind: standing_rule\nCategory: language\nSlug: chat-language\n"
        "Preference: 用中文回复。\nEvidence: 请用中文回复\n"
    )

    async def fake_params(_provider):
        return {"api_key": "test"}

    async def fake_completion(**_kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer))])

    monkeypatch.setattr(reflect, "_resolve_llm_params", fake_params)
    monkeypatch.setattr(reflect.litellm, "acompletion", fake_completion)
    monkeypatch.setattr(reflect, "get_default_provider", _no_provider)
    monkeypatch.setattr(settings, "memory_extraction_v2", True)

    prefs = await reflect.llm_extract_user_preferences(
        conversation_text="x" * 120, model="gpt-4o", max_prefs=3,
        user_turns=["我打包重启了", "直接删除", "请用中文回复"],
    )
    # assistant_behaviour and single_instruction are dropped before persistence.
    assert [p["key"] for p in prefs] == ["user_pref:chat-language"]
    assert prefs[0]["kind"] == "standing_rule"
    assert prefs[0]["evidence"] == "请用中文回复"
    assert prefs[0]["importance"] == 0.8


async def test_extractor_respects_v2_switch(monkeypatch):
    import crabagent.core.agent.reflect as reflect
    from crabagent.core.config import settings

    monkeypatch.setattr(settings, "memory_extraction_v2", False)
    prefs = await reflect.llm_extract_user_preferences(
        conversation_text="x" * 120, model="gpt-4o", user_turns=USER_TURNS,
    )
    assert prefs == []


async def _no_provider():
    return None


async def _pref_sessions(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from crabagent.core import database
    from crabagent.core.agent import memory_merge

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(database.Base.metadata.create_all)
        await database._migrate_session_memory(conn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "async_session_factory", factory)
    return factory, engine, database, memory_merge


async def test_same_key_updates_in_place_instead_of_new_row(tmp_path, monkeypatch):
    """The headline P1 fix: repeated extraction converges on one row."""
    from sqlalchemy import func, select

    factory, engine, database, _ = await _pref_sessions(tmp_path, monkeypatch)
    import crabagent.core.agent.reflect as reflect

    pref = {
        "key": "user_pref:chat-language", "category": "language", "content": "用中文回复。",
        "kind": "standing_rule", "evidence": "请用中文回复", "importance": 0.8,
        "source": "llm", "memory_type": "user_preference",
    }
    assert await reflect.persist_preferences(1, [pref]) == 1
    second = {**pref, "content": "用中文回复，代码注释保持原文。", "evidence": "用中文，注释原文"}
    assert await reflect.persist_preferences(1, [second]) == 1
    async with factory() as db:
        rows = (await db.execute(select(database.AgentMemory).where(
            database.AgentMemory.key == pref["key"]))).scalars().all()
        assert len(rows) == 1
        assert rows[0].evidence == "用中文，注释原文"
        assert rows[0].evidence_kind == "standing_rule"
        assert await db.scalar(select(func.count()).select_from(database.AgentMemory)) == 1
    await engine.dispose()


async def test_merge_accepts_non_general_category(tmp_path, monkeypatch):
    """`category == "general"` used to short-circuit every merge attempt."""
    from sqlalchemy import select

    factory, engine, database, memory_merge = await _pref_sessions(tmp_path, monkeypatch)

    async def fake_params(_p):
        return {"api_key": "test"}

    class _Resp:
        class choices:  # noqa: N801
            @staticmethod
            def _first():
                from types import SimpleNamespace
                return SimpleNamespace(message=SimpleNamespace(content='{"merge":true,"content":"合并后"}'))

    async def fake_completion(**_kwargs):
        from types import SimpleNamespace
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content='{"merge":true,"content":"合并后"}'))])

    import crabagent.core.agent.reflect as reflect
    monkeypatch.setattr(reflect, "_resolve_llm_params", fake_params)
    monkeypatch.setattr(memory_merge.litellm, "acompletion", fake_completion)
    monkeypatch.setattr(memory_merge, "embedding_similarity_score", _zero)

    async with factory.begin() as db:
        db.add(database.AgentMemory(
            user_id=1, memory_type="user_preference", key="user_pref:terse-answers",
            category="workflow", content="User prefers terse answers in chat.",
            scope="global", workspace_path="", agent_name="",
        ))
    merged = await memory_merge.merge_preference(
        1,
        {"key": "user_pref:terse-answers", "category": "workflow",
         "content": "User prefers terse answers in chat.", "importance": 0.7},
        "gpt-4o",
    )
    assert merged is True
    async with factory() as db:
        row = await db.scalar(select(database.AgentMemory).where(
            database.AgentMemory.key == "user_pref:terse-answers"))
        assert row.content == "合并后"
    await engine.dispose()


async def _zero(_a, _b):
    return 0.0


def test_category_is_not_part_of_the_key():
    """Same subject must keep one key even when the model changes its mind
    about the category (the failure mode that produced 212 hash keys)."""
    a, _ = ps.validate({**BASE, "category": "language"}, USER_TURNS)
    b, _ = ps.validate({**BASE, "category": "response_style"}, USER_TURNS)
    assert a["key"] == b["key"] == "user_pref:chat-language"
    assert a["category"] != b["category"]


@pytest.mark.parametrize("slug", ["general", "misc", "other", "preferences"])
def test_rejects_generic_slugs(slug):
    cleaned, reason = ps.validate({**BASE, "slug": slug}, USER_TURNS)
    assert cleaned is None
    assert reason.startswith("generic_slug")

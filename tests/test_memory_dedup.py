import pytest

from crabagent.core.agent.lesson_dedup import (
    looks_like_meta_lesson,
    normalize_lesson_text,
    string_similarity_score,
)
from crabagent.core.agent.reflect import persist_lesson


def test_normalize_lesson_text_collapses_case_and_whitespace():
    assert normalize_lesson_text("  Hello\n  WORLD  ") == "hello world"


def test_looks_like_meta_lesson_detects_known_garbage_patterns():
    assert looks_like_meta_lesson('{one sentence of actionable advice}"') is True
    assert looks_like_meta_lesson('We are asked to extract ONE concrete lesson from the provided completed task.') is True
    assert looks_like_meta_lesson('1.  **Analyze the Request:**\n- Goal: Extract ONE concrete lesson.') is True
    assert looks_like_meta_lesson('Use provider-specific date filters when querying time-bounded news.') is False


def test_string_similarity_score_handles_exact_and_containment_matches():
    assert string_similarity_score('abc', 'abc') == 1.0
    assert string_similarity_score('abc', 'zzabczz') > 0.4
    assert string_similarity_score('abc', 'xyz') < 0.5


@pytest.mark.asyncio
async def test_persist_lesson_reuses_existing_key_for_similar_content(monkeypatch):
    saved = []

    async def fake_get_by_agent(user_id, agent_name, limit=50):
        return [
            {
                "key": "lesson:coder:llm:existing",
                "content": "When a task requires news from a specific exact date, explicitly apply date-range filters in your web search query.",
            }
        ]

    async def fake_upsert(**kwargs):
        saved.append(kwargs)

    monkeypatch.setattr(
        "crabagent.core.database.agent_memory_get_by_agent",
        fake_get_by_agent,
    )
    monkeypatch.setattr(
        "crabagent.core.database.agent_memory_upsert",
        fake_upsert,
    )

    ok = await persist_lesson(
        user_id=1,
        agent_name="coder",
        lesson={
            "key": "lesson:coder:llm:new",
            "content": "When a task requires news from a specific exact date, explicitly apply date-range filters in your web search query and verify publication dates.",
            "category": "effective_strategy",
            "memory_type": "agent_lesson",
        },
        source_session="sess1",
    )

    assert ok is True
    assert saved
    assert saved[0]["key"] == "lesson:coder:llm:existing"


@pytest.mark.asyncio
async def test_persist_lesson_keeps_new_key_for_distinct_content(monkeypatch):
    saved = []

    async def fake_get_by_agent(user_id, agent_name, limit=50):
        return [
            {
                "key": "lesson:coder:llm:existing",
                "content": "Use date filters when searching news.",
            }
        ]

    async def fake_upsert(**kwargs):
        saved.append(kwargs)

    monkeypatch.setattr(
        "crabagent.core.database.agent_memory_get_by_agent",
        fake_get_by_agent,
    )
    monkeypatch.setattr(
        "crabagent.core.database.agent_memory_upsert",
        fake_upsert,
    )

    ok = await persist_lesson(
        user_id=1,
        agent_name="coder",
        lesson={
            "key": "lesson:coder:llm:new",
            "content": "Commit immediately before slow CPU-bound processing to avoid SQLite write locks blocking other operations.",
            "category": "effective_strategy",
            "memory_type": "agent_lesson",
        },
        source_session="sess1",
    )

    assert ok is True
    assert saved
    assert saved[0]["key"] == "lesson:coder:llm:new"


@pytest.mark.asyncio
async def test_persist_lesson_skips_meta_reflection_content(monkeypatch):
    saved = []

    async def fake_get_by_agent(user_id, agent_name, limit=80):
        return []

    async def fake_upsert(**kwargs):
        saved.append(kwargs)

    monkeypatch.setattr(
        "crabagent.core.database.agent_memory_get_by_agent",
        fake_get_by_agent,
    )
    monkeypatch.setattr(
        "crabagent.core.database.agent_memory_upsert",
        fake_upsert,
    )

    ok = await persist_lesson(
        user_id=1,
        agent_name="coder",
        lesson={
            "key": "lesson:coder:llm:meta",
            "content": 'We are asked to extract ONE concrete lesson from the provided completed task.',
            "category": "effective_strategy",
            "memory_type": "agent_lesson",
            "task_category": "analysis",
        },
        source_session="sess1",
    )

    assert ok is False
    assert saved == []


@pytest.mark.asyncio
async def test_persist_lesson_skips_analyze_request_meta_content(monkeypatch):
    saved = []

    async def fake_get_by_agent(user_id, agent_name, limit=80):
        return []

    async def fake_upsert(**kwargs):
        saved.append(kwargs)

    monkeypatch.setattr(
        "crabagent.core.database.agent_memory_get_by_agent",
        fake_get_by_agent,
    )
    monkeypatch.setattr(
        "crabagent.core.database.agent_memory_upsert",
        fake_upsert,
    )

    ok = await persist_lesson(
        user_id=1,
        agent_name="coder",
        lesson={
            "key": "lesson:coder:llm:meta-analyze",
            "content": "1.  **Analyze the Request:**\n    *   Goal: Extract ONE concrete lesson from the provided completed task.",
            "category": "effective_strategy",
            "memory_type": "agent_lesson",
            "task_category": "writing",
        },
        source_session="sess1",
    )

    assert ok is False
    assert saved == []


@pytest.mark.asyncio
async def test_persist_lesson_reuses_embedding_match_with_same_task_category(monkeypatch):
    saved = []

    async def fake_get_by_agent(user_id, agent_name, limit=80):
        return [
            {
                "key": "lesson:coder:llm:existing",
                "content": "Filter candidate lessons by task category before semantic deduplication to avoid unrelated matches.",
                "task_category": "code",
            },
            {
                "key": "lesson:coder:llm:other",
                "content": "Use date filters when searching news.",
                "task_category": "research",
            },
        ]

    async def fake_upsert(**kwargs):
        saved.append(kwargs)

    async def fake_embedding_similarity(left, right):
        if "task category" in right.lower():
            return 0.95
        return 0.10

    monkeypatch.setattr(
        "crabagent.core.database.agent_memory_get_by_agent",
        fake_get_by_agent,
    )
    monkeypatch.setattr(
        "crabagent.core.database.agent_memory_upsert",
        fake_upsert,
    )
    monkeypatch.setattr(
        "crabagent.core.agent.reflect.embedding_similarity_score",
        fake_embedding_similarity,
    )

    ok = await persist_lesson(
        user_id=1,
        agent_name="coder",
        lesson={
            "key": "lesson:coder:llm:new",
            "content": "Before semantic deduplication, narrow comparisons to the same task category so unrelated memories are not merged.",
            "category": "effective_strategy",
            "memory_type": "agent_lesson",
            "task_category": "code",
        },
        source_session="sess1",
    )

    assert ok is True
    assert saved
    assert saved[0]["key"] == "lesson:coder:llm:existing"
    assert saved[0]["task_category"] == "code"

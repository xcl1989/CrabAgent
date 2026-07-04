from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from crabagent.core.agent import reflect


class TestReflectHelpers:
    def test_classify_task_returns_general_for_unknown_text(self):
        assert reflect.classify_task("just chatting about weather") == "general"

    def test_rule_extract_lesson_returns_none_when_iterations_low(self):
        assert reflect.rule_extract_lesson("coder", 1, 10, "task", "result") is None

    def test_extract_response_text_prefers_message_content(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="answer", reasoning_content="thinking"))]
        )

        assert reflect._extract_response_text(response) == "answer"

    def test_extract_response_text_uses_reasoning_fallback(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="", reasoning_content="hidden response final answer"))]
        )

        assert "final answer" in reflect._extract_response_text(response)

    def test_is_generic_praise_detects_known_phrases(self):
        assert reflect._is_generic_praise("Successfully completed the task in time") is True
        assert reflect._is_generic_praise("Use smaller commits before refactors") is False


class TestLLMReflectLesson:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_provider(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(reflect, "_resolve_llm_params", _async_return(None))

        result = await reflect.llm_reflect_lesson(
            agent_name="coder",
            task="fix bug",
            result="done",
            task_category="code",
            stats={"iterations": 2, "tokens": 10, "elapsed": 1.2},
            model="gpt-4o",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_parses_insight_and_uses_failed_approach_for_errors(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(reflect, "_resolve_llm_params", _async_return({"api_key": "k"}))

        async def fake_acompletion(**kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="Category: code\nInsight: Check file existence before destructive writes",
                            reasoning_content="",
                        )
                    )
                ]
            )

        monkeypatch.setattr(reflect, "litellm", SimpleNamespace(acompletion=fake_acompletion))

        result = await reflect.llm_reflect_lesson(
            agent_name="coder",
            task="fix bug",
            result="",
            task_category="code",
            stats={"iterations": 2, "tokens": 10, "elapsed": 1.2},
            model="gpt-4o",
            error_msg="boom",
        )

        assert result["category"] == "failed_approach"
        assert result["task_category"] == "code"
        assert "Check file existence" in result["content"]
        assert result["importance"] == 0.85

    @pytest.mark.asyncio
    async def test_rejects_generic_praise(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(reflect, "_resolve_llm_params", _async_return({"api_key": "k"}))

        async def fake_acompletion(**kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="Insight: Successfully completed the task", reasoning_content=""))]
            )

        monkeypatch.setattr(reflect, "litellm", SimpleNamespace(acompletion=fake_acompletion))

        result = await reflect.llm_reflect_lesson(
            agent_name="coder",
            task="fix bug",
            result="done",
            task_category="code",
            stats={"iterations": 2, "tokens": 10, "elapsed": 1.2},
            model="gpt-4o",
        )

        assert result is None


class TestPreferenceExtraction:
    @pytest.mark.asyncio
    async def test_skips_short_conversations(self):
        result = await reflect.llm_extract_user_preferences("too short", model="gpt-4o")

        assert result == []

    @pytest.mark.asyncio
    async def test_extracts_multiple_preferences(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(reflect, "_resolve_llm_params", _async_return({"api_key": "k"}))

        async def fake_acompletion(**kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                "Category: language\nPreference: User prefers Chinese for chat.\n\n"
                                "Category: format\nPreference: User wants JSON output when possible."
                            ),
                            reasoning_content="",
                        )
                    )
                ]
            )

        monkeypatch.setattr(reflect, "litellm", SimpleNamespace(acompletion=fake_acompletion))

        convo = "User: 请用中文回复，并尽量输出 JSON 格式。" * 20
        prefs = await reflect.llm_extract_user_preferences(convo, model="gpt-4o", max_prefs=2)

        assert len(prefs) == 2
        assert prefs[0]["category"] == "language"
        assert "Chinese" in prefs[0]["content"]
        assert prefs[1]["category"] == "format"

    @pytest.mark.asyncio
    async def test_filters_bad_or_too_short_preferences(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(reflect, "_resolve_llm_params", _async_return({"api_key": "k"}))

        async def fake_acompletion(**kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                "Category: general\nPreference: none\n\n"
                                "Category: style\nPreference: short\n\n"
                                "Category: style\nPreference: User prefers concise summaries."
                            ),
                            reasoning_content="",
                        )
                    )
                ]
            )

        monkeypatch.setattr(reflect, "litellm", SimpleNamespace(acompletion=fake_acompletion))

        convo = "User keeps asking for concise summaries and says no fluff please." * 10
        prefs = await reflect.llm_extract_user_preferences(convo, model="gpt-4o")

        assert len(prefs) == 1
        assert prefs[0]["category"] == "style"


class TestPersistenceHelpers:
    @pytest.mark.asyncio
    async def test_persist_lesson_skips_meta_content(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(reflect, "looks_like_meta_lesson", lambda content: True)

        ok = await reflect.persist_lesson(
            user_id=1,
            agent_name="coder",
            lesson={"key": "k1", "content": "meta lesson", "category": "effective_strategy"},
        )

        assert ok is False

    @pytest.mark.asyncio
    async def test_persist_lesson_reuses_key_on_string_dedup(self, monkeypatch: pytest.MonkeyPatch):
        saved = {}

        async def fake_get_by_agent(*args, **kwargs):
            return [{"key": "existing-key", "content": "Use small commits", "task_category": "code"}]

        async def fake_upsert(**kwargs):
            saved.update(kwargs)

        monkeypatch.setattr("crabagent.core.database.agent_memory_get_by_agent", fake_get_by_agent)
        monkeypatch.setattr("crabagent.core.database.agent_memory_upsert", fake_upsert)
        monkeypatch.setattr(reflect, "_enforce_lesson_cap", _async_return(None))
        monkeypatch.setattr(reflect, "looks_like_meta_lesson", lambda content: False)
        monkeypatch.setattr(reflect, "normalize_lesson_text", lambda text: text.lower())
        monkeypatch.setattr(reflect, "string_similarity_score", lambda a, b: 0.99)

        ok = await reflect.persist_lesson(
            user_id=1,
            agent_name="coder",
            lesson={
                "key": "new-key",
                "content": "Use small commits",
                "category": "effective_strategy",
                "task_category": "code",
            },
            source_session="sess-1",
        )

        assert ok is True
        assert saved["key"] == "existing-key"
        assert saved["source_session"] == "sess-1"

    @pytest.mark.asyncio
    async def test_persist_preferences_counts_only_successes(self, monkeypatch: pytest.MonkeyPatch):
        calls = {"count": 0}

        async def fake_upsert(**kwargs):
            calls["count"] += 1
            if kwargs["key"] == "bad":
                raise RuntimeError("fail")

        monkeypatch.setattr("crabagent.core.database.agent_memory_upsert", fake_upsert)

        saved = await reflect.persist_preferences(
            1,
            [
                {"key": "good", "content": "Use Chinese", "category": "language"},
                {"key": "bad", "content": "Broken pref", "category": "general"},
            ],
            source_session="sess-1",
        )

        assert calls["count"] == 2
        assert saved == 1


def _async_return(value):
    async def inner(*args, **kwargs):
        return value

    return inner

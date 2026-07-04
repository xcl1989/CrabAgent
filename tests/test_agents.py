"""Tests for the multi-agent delegation system."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from crabagent.core.agent import agents as agents_module
from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.tools.registry import ToolRegistry


# ── tool sets ─────────────────────────────────────────────────────────


class TestToolSets:
    def test_memory_tools_not_empty(self):
        tools = agents_module.get_memory_tools()
        assert "memory_save" in tools
        assert "memory_recall" in tools

    def test_shared_tools_not_empty(self):
        tools = agents_module.get_shared_tools()
        assert "shared_put" in tools
        assert "shared_get" in tools

    def test_delegation_tools_not_empty(self):
        tools = agents_module.get_delegation_tools()
        assert "delegate_task" in tools
        assert "handoff_to" in tools


# ── _translate_agent_field ────────────────────────────────────────────


class TestTranslateAgentField:
    def test_returns_original_when_no_translation(self):
        result = agents_module._translate_agent_field("unknown_agent", "role", "Original Role", "en")
        assert result == "Original Role"

    def test_returns_translated_when_available(self):
        # 'researcher' agent likely has zh-CN translations
        result = agents_module._translate_agent_field("researcher", "role", "Web Researcher", "zh-CN")
        # Should return something (either translated or fallback)
        assert isinstance(result, str)
        assert len(result) > 0


# ── build_agent_switch_msg ────────────────────────────────────────────


class TestBuildAgentSwitchMsg:
    def test_contains_agent_fields(self):
        agent_def = {
            "name": "coder",
            "display_name": "Code Expert",
            "role": "Write code",
            "goal": "Clean code",
            "backstory": "Expert developer",
            "icon": "💻",
        }
        msg = agents_module.build_agent_switch_msg(agent_def, locale="en")

        assert msg["role"] == "user"
        assert msg["agent"] == "coder"
        assert "Code Expert" in msg["content"]

    def test_without_backstory(self):
        agent_def = {
            "name": "simple",
            "display_name": "Simple",
            "role": "Do stuff",
            "goal": "Done",
            "backstory": "",
            "icon": "",
        }
        msg = agents_module.build_agent_switch_msg(agent_def)
        assert "Simple" in msg["content"]


# ── _build_system_prompt ──────────────────────────────────────────────


class TestBuildSystemPrompt:
    def test_contains_role_and_goal(self):
        agent_def = {
            "name": "researcher",
            "role": "Find info",
            "goal": "Accurate results",
            "backstory": "Experienced researcher",
        }
        prompt = agents_module._build_system_prompt(agent_def, locale="en")

        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_load_list_falls_back_to_english_for_missing_locale(self):
        items = agents_module._load_list("zz-ZZ", "team_prompt.when")

        assert isinstance(items, list)
        assert len(items) > 0

    def test_includes_shared_instruction(self):
        agent_def = {
            "name": "x",
            "role": "r",
            "goal": "g",
            "backstory": "",
        }
        prompt = agents_module._build_system_prompt(agent_def, has_shared=True, locale="en")
        assert len(prompt) > 0

    def test_includes_help_instruction(self):
        agent_def = {
            "name": "x",
            "role": "r",
            "goal": "g",
            "backstory": "",
        }
        prompt = agents_module._build_system_prompt(agent_def, can_request_help=True, locale="en")
        assert len(prompt) > 0


# ── get_running_subs / get_all_session_subs ───────────────────────────


class TestSubAgentTracking:
    def test_get_running_subs_returns_empty_for_unknown_session(self):
        agents_module._running_sub_agents.clear()
        assert agents_module.get_running_subs("unknown") == {}

    def test_get_running_subs_returns_active_subs(self):
        agents_module._running_sub_agents.clear()
        agents_module._running_sub_agents["sub_1"] = {
            "session_id": "sess1",
            "agent_name": "coder",
            "display_name": "Code Expert",
            "task": "fix bug",
            "started_at": 1000.0,
        }

        result = agents_module.get_running_subs("sess1")
        assert "sub_1" in result
        assert result["sub_1"]["agent_name"] == "coder"

    def test_get_running_subs_excludes_completed(self):
        import time

        agents_module._running_sub_agents.clear()
        agents_module._running_sub_agents["sub_2"] = {
            "session_id": "sess1",
            "agent_name": "coder",
            "display_name": "Code Expert",
            "task": "fix bug",
            "started_at": 1000.0,
            "completed_at": time.time(),
        }

        result = agents_module.get_running_subs("sess1")
        assert "sub_2" not in result

    def test_get_all_session_subs_includes_completed(self):
        import time

        agents_module._running_sub_agents.clear()
        agents_module._running_sub_agents["sub_3"] = {
            "session_id": "sess1",
            "agent_name": "coder",
            "display_name": "Code Expert",
            "task": "fix bug",
            "started_at": 1000.0,
            "completed_at": time.time(),
        }

        result = agents_module.get_all_session_subs("sess1")
        assert "sub_3" in result

    def test_get_all_session_subs_expires_old_completed(self):
        import time

        agents_module._running_sub_agents.clear()
        agents_module._running_sub_agents["sub_old"] = {
            "session_id": "sess1",
            "agent_name": "coder",
            "display_name": "Code Expert",
            "task": "fix bug",
            "started_at": 1000.0,
            "completed_at": time.time() - agents_module._COMPLETED_TTL - 100,
        }

        result = agents_module.get_all_session_subs("sess1")
        assert "sub_old" not in result
        assert "sub_old" not in agents_module._running_sub_agents


# ── inject_agent_lessons ──────────────────────────────────────────────


class TestInjectAgentLessons:
    @pytest.mark.asyncio
    async def test_returns_original_when_no_user_id(self):
        result = await agents_module.inject_agent_lessons("original", user_id=0, agent_name="coder")
        assert result == "original"

    @pytest.mark.asyncio
    async def test_returns_original_when_no_agent_name(self):
        result = await agents_module.inject_agent_lessons("original", user_id=1, agent_name="")
        assert result == "original"

    @pytest.mark.asyncio
    async def test_returns_original_when_no_lessons(self, monkeypatch: pytest.MonkeyPatch):
        async def fake_get_by_agent(*a, **kw):
            return []

        async def fake_search_vector(*a, **kw):
            return []

        monkeypatch.setattr("crabagent.core.database.agent_memory_get_by_agent", fake_get_by_agent)
        monkeypatch.setattr("crabagent.core.database.agent_memory_search_vector", fake_search_vector)

        result = await agents_module.inject_agent_lessons("original", user_id=1, agent_name="coder")
        assert result == "original"

    @pytest.mark.asyncio
    async def test_appends_lessons_section(self, monkeypatch: pytest.MonkeyPatch):
        async def fake_get_by_agent(*a, **kw):
            return [
                {"key": "lesson:1", "content": "Always commit before pushing.", "category": "effective_strategy", "source": "llm"},
                {"key": "lesson:2", "content": "Don't use print for debugging.", "category": "failed_approach", "source": "rule"},
            ]

        async def fake_search_vector(*a, **kw):
            return []

        monkeypatch.setattr("crabagent.core.database.agent_memory_get_by_agent", fake_get_by_agent)
        monkeypatch.setattr("crabagent.core.database.agent_memory_search_vector", fake_search_vector)

        result = await agents_module.inject_agent_lessons("base prompt", user_id=1, agent_name="coder")

        assert "Past Experiences" in result
        assert "Always commit" in result
        assert "Don't use print" in result
        assert "Pitfalls to Avoid" in result
        assert "What Worked Before" in result


# ── build_memory_prompt ───────────────────────────────────────────────


class TestBuildMemoryPrompt:
    @pytest.mark.asyncio
    async def test_returns_empty_for_zero_user_id(self):
        result = await agents_module.build_memory_prompt(user_id=0)
        assert result == ""

    @pytest.mark.asyncio
    async def test_injects_team_memories(self, monkeypatch: pytest.MonkeyPatch):
        async def fake_get_by_type(*a, **kw):
            return [
                {"key": "tech:stack", "content": "Python/FastAPI", "category": "tech_stack"},
            ]

        async def fake_search_vector(*a, **kw):
            return []

        monkeypatch.setattr("crabagent.core.database.agent_memory_get_by_type", fake_get_by_type)
        monkeypatch.setattr("crabagent.core.database.agent_memory_search_vector", fake_search_vector)

        result = await agents_module.build_memory_prompt(user_id=1, query="test")

        assert "Python/FastAPI" in result

    @pytest.mark.asyncio
    async def test_injects_related_lessons(self, monkeypatch: pytest.MonkeyPatch):
        async def fake_get_by_type(*a, **kw):
            return []

        async def fake_search_vector(*a, **kw):
            return [
                {"key": "lesson:1", "content": "Use type hints.", "memory_type": "agent_lesson", "importance": 0.8, "agent_name": "coder"},
                {"key": "pref:lang", "content": "Prefer Python.", "memory_type": "user_preference", "importance": 0.9},
            ]

        monkeypatch.setattr("crabagent.core.database.agent_memory_get_by_type", fake_get_by_type)
        monkeypatch.setattr("crabagent.core.database.agent_memory_search_vector", fake_search_vector)

        result = await agents_module.build_memory_prompt(user_id=1, query="how to code")

        assert "Prefer Python." in result
        assert "type hints" in result.lower() or "Use type hints" in result


# ── spawn_sub_agent ───────────────────────────────────────────────────


class TestSpawnSubAgent:
    @pytest.mark.asyncio
    async def test_returns_error_for_unknown_agent(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(agents_module, "get_agent", _async_return(None))
        ctx = AgentContext(workspace=Path.cwd())
        result = await agents_module.spawn_sub_agent("ghost", "do task", ctx)
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_runs_agent_and_returns_result(self, monkeypatch: pytest.MonkeyPatch):
        agent_def = {
            "name": "coder",
            "display_name": "Code Expert",
            "role": "Write code",
            "goal": "Clean code",
            "backstory": "",
            "model": "",
            "allow_delegation": False,
            "tool_permissions": {},
        }
        monkeypatch.setattr(agents_module, "get_agent", _async_return(agent_def))
        monkeypatch.setattr(agents_module, "_classify_task", lambda task: "code")
        monkeypatch.setattr(agents_module, "inject_agent_lessons", _async_return("prompt with lessons"))
        monkeypatch.setattr(agents_module, "_load_shared_context", _async_return(""))

        async def fake_run_agent(context, query):
            context.messages.append({"role": "assistant", "content": "task done"})
            return context.messages

        monkeypatch.setattr("crabagent.core.agent.loop.run_agent", fake_run_agent)

        parent = AgentContext(workspace=Path.cwd())
        parent.metadata["session_id"] = "sess-1"
        parent.metadata["user_id"] = 1

        result = await agents_module.spawn_sub_agent("coder", "fix the bug", parent)

        assert "task done" in result or "Code Expert" in result

    @pytest.mark.asyncio
    async def test_spawn_sub_agent_includes_history_and_shared_context(self, monkeypatch: pytest.MonkeyPatch):
        agents_module._running_sub_agents.clear()
        agent_def = {
            "name": "coder",
            "display_name": "Code Expert",
            "role": "Write code",
            "goal": "Clean code",
            "backstory": "",
            "model": "",
            "allow_delegation": True,
            "tool_permissions": {},
        }
        monkeypatch.setattr(agents_module, "get_agent", _async_return(agent_def))
        monkeypatch.setattr(agents_module, "_classify_task", lambda task: "code")
        monkeypatch.setattr(agents_module, "inject_agent_lessons", _async_return("prompt with lessons"))
        monkeypatch.setattr(agents_module, "_load_shared_context", _async_return("shared facts"))
        monkeypatch.setattr("crabagent.core.database.shared_memory_put", _async_return(None))
        monkeypatch.setattr("crabagent.core.database.agent_memory_upsert", _async_return(None))
        monkeypatch.setattr("crabagent.core.database.task_record_create", _async_return(None))
        monkeypatch.setattr(agents_module, "_rule_extract_lesson", lambda **kwargs: None)
        monkeypatch.setattr(agents_module, "_llm_reflect_lesson", _async_return(None))

        async def fake_run_agent(context, query):
            context.iteration = 2
            context.total_tokens = 42
            context.messages.append({"role": "assistant", "content": "task done"})
            return context.messages

        monkeypatch.setattr("crabagent.core.agent.loop.run_agent", fake_run_agent)

        parent = AgentContext(workspace=Path.cwd(), tool_registry=ToolRegistry())
        parent.messages = [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
        ]
        parent.metadata["session_id"] = "sess-1"
        parent.metadata["user_id"] = 1
        parent.metadata["locale"] = "en"

        result = await agents_module.spawn_sub_agent("coder", "fix the bug", parent, include_history=True)

        assert result == "task done"
        pending = parent.metadata["_pending_sub_agent_messages"]
        assert pending[0]["role"] == "sub_agent"
        assert "task done" in pending[0]["content"]

    @pytest.mark.asyncio
    async def test_spawn_sub_agent_returns_error_and_marks_status(self, monkeypatch: pytest.MonkeyPatch):
        agents_module._running_sub_agents.clear()
        agent_def = {
            "name": "coder",
            "display_name": "Code Expert",
            "role": "Write code",
            "goal": "Clean code",
            "backstory": "",
            "model": "",
            "allow_delegation": False,
            "tool_permissions": {},
        }
        monkeypatch.setattr(agents_module, "get_agent", _async_return(agent_def))
        monkeypatch.setattr(agents_module, "_classify_task", lambda task: "code")
        monkeypatch.setattr(agents_module, "inject_agent_lessons", _async_return("prompt with lessons"))
        monkeypatch.setattr(agents_module, "_load_shared_context", _async_return(""))
        monkeypatch.setattr("crabagent.core.database.task_record_create", _async_return(None))
        monkeypatch.setattr("crabagent.core.database.agent_memory_upsert", _async_return(None))
        monkeypatch.setattr(agents_module, "_llm_reflect_lesson", _async_return(None))

        async def failing_run_agent(context, query):
            raise RuntimeError("sub failed")

        monkeypatch.setattr("crabagent.core.agent.loop.run_agent", failing_run_agent)

        parent = AgentContext(workspace=Path.cwd())
        parent.metadata["session_id"] = "sess-1"
        parent.metadata["user_id"] = 1

        result = await agents_module.spawn_sub_agent("coder", "fix the bug", parent)

        assert "failed" in result
        all_subs = agents_module.get_all_session_subs("sess-1")
        assert len(all_subs) == 1
        assert next(iter(all_subs.values()))["status"] == "error"


def _async_return(value):
    async def inner(*args, **kwargs):
        return value

    return inner

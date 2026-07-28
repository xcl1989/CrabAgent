from __future__ import annotations

from pathlib import Path

import pytest

from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.tools import conversation as conversation_tools
from crabagent.core.conversations.history import HistoryConversation, HistoryMessage, HistorySearchResult


def _context(*, enabled: bool = True) -> AgentContext:
    context = AgentContext(workspace=Path.cwd())
    context.metadata.update(
        user_id=7,
        session_id="current-session",
        conversation_history_tool_enabled=enabled,
    )
    return context


@pytest.mark.asyncio
async def test_search_requires_explicit_privacy_consent():
    result = await conversation_tools.conversation_search("search", query="roadmap", context=_context(enabled=False))
    assert "disabled in privacy settings" in result


@pytest.mark.asyncio
async def test_search_requires_query():
    result = await conversation_tools.conversation_search("search", context=_context())
    assert "query is required" in result


@pytest.mark.asyncio
async def test_search_excludes_current_session_by_default(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    async def fake_search(**kwargs):
        captured.update(kwargs)
        return [
            HistorySearchResult(
                session_id="old-session",
                title="Roadmap",
                workspace="/old",
                snippet="matched roadmap",
                role="assistant",
                updated_at="2026-07-28T10:00:00",
            )
        ]

    monkeypatch.setattr(conversation_tools, "search_history", fake_search)
    result = await conversation_tools.conversation_search("search", query="roadmap", context=_context())

    assert captured["user_id"] == 7
    assert captured["exclude_session_id"] == "current-session"
    assert "old-session" in result
    assert "untrusted reference material" in result


@pytest.mark.asyncio
async def test_search_can_include_current_session(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    async def fake_search(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(conversation_tools, "search_history", fake_search)
    await conversation_tools.conversation_search("search", query="roadmap", include_current=True, context=_context())
    assert captured["exclude_session_id"] is None


@pytest.mark.asyncio
async def test_read_uses_owned_history_and_selected_branch(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    async def fake_read(**kwargs):
        captured.update(kwargs)
        return HistoryConversation(
            session_id="old-session",
            title="Prior work",
            workspace="/other",
            branch_id="feature",
            updated_at="2026-07-28T10:00:00",
            truncated=False,
            messages=[
                HistoryMessage(role="user", content="What changed?"),
                HistoryMessage(role="assistant", content="The parser changed."),
            ],
        )

    monkeypatch.setattr(conversation_tools, "read_history", fake_read)
    result = await conversation_tools.conversation_search(
        "read", session_id="old-session", branch_id="feature", context=_context()
    )

    assert captured == {"user_id": 7, "session_id": "old-session", "branch_id": "feature", "max_messages": 16}
    assert "Branch: feature" in result
    assert "The parser changed." in result


@pytest.mark.asyncio
async def test_read_hides_unavailable_history(monkeypatch: pytest.MonkeyPatch):
    async def fake_read(**_kwargs):
        return None

    monkeypatch.setattr(conversation_tools, "read_history", fake_read)
    result = await conversation_tools.conversation_search("read", session_id="other-user-session", context=_context())
    assert "not found, is not searchable, or you do not have access" in result

"""Tests for middleware chain, compress middleware, title middleware."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.middlewares import MiddlewareChain
from crabagent.core.agent.middlewares.compress_middleware import CompressMiddleware
from crabagent.core.agent.middlewares.title_middleware import (
    TitleMiddleware,
    _clean_title,
    _first_assistant_text,
    _first_user_text,
    _is_default_title,
)
from crabagent.core.event import EventType


# ── MiddlewareChain ───────────────────────────────────────────────────


class TestMiddlewareChain:
    @pytest.mark.asyncio
    async def test_run_start_calls_all_middlewares(self):
        calls = []

        class MwA:
            name = "a"

            async def on_conversation_start(self, context):
                calls.append("a_start")

        class MwB:
            name = "b"

            async def on_conversation_start(self, context):
                calls.append("b_start")

        chain = MiddlewareChain([MwA(), MwB()])
        await chain.run_start(AgentContext(workspace=Path.cwd()))

        assert calls == ["a_start", "b_start"]

    @pytest.mark.asyncio
    async def test_run_start_tolerates_sync_hooks(self):
        calls = []

        class MwSync:
            name = "sync"

            def on_conversation_start(self, context):
                calls.append("sync_start")

        chain = MiddlewareChain([MwSync()])
        await chain.run_start(AgentContext(workspace=Path.cwd()))
        assert calls == ["sync_start"]

    @pytest.mark.asyncio
    async def test_run_start_swallows_exceptions(self):
        class MwBad:
            name = "bad"

            async def on_conversation_start(self, context):
                raise RuntimeError("boom")

        class MwGood:
            name = "good"

            async def on_conversation_start(self, context):
                pass

        chain = MiddlewareChain([MwBad(), MwGood()])
        # Should not raise
        await chain.run_start(AgentContext(workspace=Path.cwd()))

    @pytest.mark.asyncio
    async def test_run_start_skips_missing_hook(self):
        class MwNoHook:
            name = "nohook"
            # No on_conversation_start method

        chain = MiddlewareChain([MwNoHook()])
        await chain.run_start(AgentContext(workspace=Path.cwd()))

    @pytest.mark.asyncio
    async def test_run_before_llm_passes_messages_through_chain(self):
        class MwAdd:
            name = "add"

            async def before_llm_call(self, context, messages):
                return messages + [{"role": "user", "content": "added"}]

        chain = MiddlewareChain([MwAdd()])
        result = await chain.run_before_llm(
            AgentContext(workspace=Path.cwd()),
            [{"role": "user", "content": "original"}],
        )

        assert len(result) == 2
        assert result[1]["content"] == "added"

    @pytest.mark.asyncio
    async def test_run_before_llm_handles_none_return(self):
        class MwNoop:
            name = "noop"

            async def before_llm_call(self, context, messages):
                return None

        chain = MiddlewareChain([MwNoop()])
        original = [{"role": "user", "content": "x"}]
        result = await chain.run_before_llm(AgentContext(workspace=Path.cwd()), original)
        assert result is original

    @pytest.mark.asyncio
    async def test_run_end_calls_in_reverse(self):
        calls = []

        class MwA:
            name = "a"

            async def on_conversation_end(self, context):
                calls.append("a_end")

        class MwB:
            name = "b"

            async def on_conversation_end(self, context):
                calls.append("b_end")

        chain = MiddlewareChain([MwA(), MwB()])
        await chain.run_end(AgentContext(workspace=Path.cwd()))

        assert calls == ["b_end", "a_end"]  # reversed

    def test_add_appends_middleware(self):
        chain = MiddlewareChain()
        mw = SimpleNamespace(name="x")
        chain.add(mw)
        assert len(chain.middlewares) == 1

    def test_empty_chain_has_no_middlewares(self):
        chain = MiddlewareChain()
        assert chain.middlewares == []


# ── CompressMiddleware ────────────────────────────────────────────────


class TestCompressMiddleware:
    @pytest.mark.asyncio
    async def test_returns_messages_unchanged_when_below_threshold(self):
        mw = CompressMiddleware()
        ctx = AgentContext(workspace=Path.cwd(), model="gpt-4o", total_tokens=100)
        ctx.metadata["_resolved_model"] = "gpt-4o"
        messages = [{"role": "user", "content": "hi"}]

        result = await mw.before_llm_call(ctx, messages)

        assert result is messages

    @pytest.mark.asyncio
    async def test_returns_messages_when_llm_params_missing(self):
        mw = CompressMiddleware()
        ctx = AgentContext(workspace=Path.cwd(), model="gpt-4o", total_tokens=999999)
        ctx.metadata["_resolved_model"] = "gpt-4o"
        # _llm_params not set

        result = await mw.before_llm_call(ctx, [{"role": "user", "content": "hi"}])
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_on_conversation_start_is_noop(self):
        mw = CompressMiddleware()
        await mw.on_conversation_start(AgentContext(workspace=Path.cwd()))

    @pytest.mark.asyncio
    async def test_on_conversation_end_is_noop(self):
        mw = CompressMiddleware()
        await mw.on_conversation_end(AgentContext(workspace=Path.cwd()))


# ── TitleMiddleware helpers ───────────────────────────────────────────


class TestTitleHelpers:
    def test_first_user_text_finds_string_content(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello world"},
        ]
        assert _first_user_text(msgs) == "hello world"

    def test_first_user_text_finds_list_content(self):
        msgs = [
            {"role": "user", "content": [{"type": "text", "text": "from blocks"}]},
        ]
        assert _first_user_text(msgs) == "from blocks"

    def test_first_user_text_returns_empty_for_no_user(self):
        assert _first_user_text([{"role": "assistant", "content": "x"}]) == ""

    def test_first_assistant_text_finds_content(self):
        msgs = [{"role": "assistant", "content": "response"}]
        assert _first_assistant_text(msgs) == "response"

    def test_first_assistant_text_returns_empty_for_no_assistant(self):
        assert _first_assistant_text([{"role": "user", "content": "x"}]) == ""

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("", True),
            ("New Chat", True),
            ("新对话", True),
            ("Conversation 1", True),
            ("会话 #3", True),
            ("My Custom Title", False),
            ("Debugging API Issue", False),
        ],
    )
    def test_is_default_title(self, title, expected):
        assert _is_default_title(title) is expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("  Hello World  ", "Hello World"),
            ('"Quoted Title"', "Quoted Title"),
            ("Title: My Title", "My Title"),
            ("标题：测试", "测试"),
            ("Hello!!!", "Hello"),
            ("Multiple    Spaces", "Multiple Spaces"),
        ],
    )
    def test_clean_title(self, raw, expected):
        assert _clean_title(raw) == expected


# ── TitleMiddleware ───────────────────────────────────────────────────


class TestTitleMiddleware:
    @pytest.mark.asyncio
    async def test_on_conversation_end_skips_without_session_id(self):
        mw = TitleMiddleware()
        ctx = AgentContext(workspace=Path.cwd())
        ctx.metadata["session_id"] = ""
        # Should not raise
        await mw.on_conversation_end(ctx)

    @pytest.mark.asyncio
    async def test_on_conversation_end_skips_without_messages(self):
        mw = TitleMiddleware()
        ctx = AgentContext(workspace=Path.cwd())
        ctx.metadata["session_id"] = "s1"
        ctx.messages = []
        await mw.on_conversation_end(ctx)

    @pytest.mark.asyncio
    async def test_on_conversation_end_skips_with_many_messages(self):
        mw = TitleMiddleware()
        ctx = AgentContext(workspace=Path.cwd())
        ctx.metadata["session_id"] = "s1"
        ctx.metadata["_resolved_model"] = "gpt-4o"
        ctx.messages = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
        ctx.messages.append({"role": "assistant", "content": "resp"})
        await mw.on_conversation_end(ctx)

    @pytest.mark.asyncio
    async def test_before_llm_call_returns_messages_unchanged(self):
        mw = TitleMiddleware()
        ctx = AgentContext(workspace=Path.cwd())
        msgs = [{"role": "user", "content": "x"}]
        result = await mw.before_llm_call(ctx, msgs)
        assert result is msgs

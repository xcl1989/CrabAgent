from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import litellm

from crabagent.core.agent import compress
from crabagent.core.agent.context import AgentContext
from crabagent.core.event import EventType


class FakeChunk:
    def __init__(self, content=None, reasoning=None, choices=None, usage=None):
        self.usage = usage
        if choices is None:
            delta = SimpleNamespace(content=content, reasoning_content=reasoning)
            self.choices = [SimpleNamespace(delta=delta, finish_reason=None if content else "stop")]
        else:
            self.choices = choices


class FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        async def gen():
            for c in self._chunks:
                yield c

        return gen()


@pytest.mark.asyncio
async def test_compress_context_skips_when_too_few_messages():
    context = AgentContext(workspace=Path.cwd(), messages=[{"role": "user", "content": "a"}])

    await compress.compress_context(context, {}, "gpt-4o")

    assert len(context.messages) == 1


@pytest.mark.asyncio
async def test_compress_context_replaces_messages_with_summary(monkeypatch: pytest.MonkeyPatch):
    context = AgentContext(
        workspace=Path.cwd(),
        system_prompt="sys",
        messages=(
            [
                {"role": "user", "content": "one"},
                {"role": "assistant", "content": "two"},
                {"role": "user", "content": "three"},
                {"role": "assistant", "content": "four"},
                {"role": "user", "content": "five"},
                {"role": "assistant", "content": "six"},
                {"role": "user", "content": "seven"},
                {"role": "assistant", "content": "eight"},
                {"role": "user", "content": "nine"},
                {"role": "assistant", "content": "ten"},
            ]
        ),
    )
    events = []
    context.event_bus.subscribe(lambda event: events.append(event))

    async def fake_acompletion(**kwargs):
        return FakeStream([FakeChunk(content="SUMMARY TEXT"), FakeChunk(content=None)])

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    await compress.compress_context(context, {}, "gpt-4o")

    roles = [msg["role"] for msg in context.messages]
    assert roles[0] == "compress"
    assert roles[1] == "assistant"
    assert context.messages[0]["content"] == "SUMMARY TEXT"
    assert any(event.type == EventType.COMPRESS_START for event in events)
    assert any(event.type == EventType.CONTEXT_COMPRESSED for event in events)
    assert context.total_tokens == 0


@pytest.mark.asyncio
async def test_compress_context_emits_failed_event_on_error(monkeypatch: pytest.MonkeyPatch):
    context = AgentContext(
        workspace=Path.cwd(),
        messages=[{"role": "user", "content": str(i)} for i in range(20)],
    )
    events = []
    context.event_bus.subscribe(lambda event: events.append(event))

    async def fake_acompletion(**kwargs):
        raise ValueError("bad")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    await compress.compress_context(context, {}, "gpt-4o")

    compressed_event = next(event for event in events if event.type == EventType.CONTEXT_COMPRESSED)
    assert compressed_event.data.get("failed") is True
    assert len(context.messages) == 20


@pytest.mark.asyncio
async def test_compress_context_retries_on_rate_limit(monkeypatch: pytest.MonkeyPatch):
    context = AgentContext(
        workspace=Path.cwd(),
        messages=[{"role": "user", "content": str(i)} for i in range(20)],
    )
    call_count = {"n": 0}

    async def fake_acompletion(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise litellm.exceptions.RateLimitError(
                message="slow down",
                llm_provider="openai",
                model="gpt-4o",
            )
        return FakeStream([FakeChunk(content="OK SUMMARY")])

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(compress.asyncio, "sleep", _async_noop)

    await compress.compress_context(context, {}, "gpt-4o")

    assert call_count["n"] == 2
    assert context.messages[0]["content"] == "OK SUMMARY"


async def _async_noop(*args, **kwargs):
    return None

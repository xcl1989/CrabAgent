from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import crabagent.core.agent.loop as loop
from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.tools.registry import ToolRegistry
from crabagent.core.event import EventType


def test_preview_result_handles_text_lists_and_images():
    result = loop._preview_result(
        [
            {"type": "text", "text": "hello"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,xxx"}},
            {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
        ]
    )

    assert "hello" in result
    assert "[image embedded]" in result
    assert "https://example.com" in result


def test_truncate_result_truncates_text_blocks_only():
    out = loop._truncate_result(
        [
            {"type": "text", "text": "A" * 50},
            {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
        ],
        10,
    )

    assert out[0]["text"].endswith("[truncated]")
    assert out[1]["image_url"]["url"] == "https://example.com/a.png"


def test_build_messages_converts_multimodal_content_for_non_vision_model():
    context = AgentContext(
        workspace=Path.cwd(),
        model="deepseek-chat",
        system_prompt="system",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "look"},
                    {"type": "image_url", "file_path": "/tmp/a.png", "mime": "image/png", "size_kb": 9},
                ],
                "agent": "default",
            },
            {"role": "stats", "content": "skip me"},
        ],
    )

    messages = loop._build_messages(context)

    assert messages[0] == {"role": "system", "content": "system"}
    assert "[Attached image: /tmp/a.png (image/png, 9KB)]" in messages[1]["content"]
    assert all(msg["role"] != "stats" for msg in messages)


def test_build_messages_strips_orphan_tool_calls():
    context = AgentContext(
        workspace=Path.cwd(),
        model="gpt-4o",
        messages=[
            {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
            {"role": "user", "content": "next"},
        ],
    )

    messages = loop._build_messages(context)

    assert "tool_calls" not in messages[0]


def test_build_messages_keeps_multimodal_content_for_vision_model():
    context = AgentContext(
        workspace=Path.cwd(),
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    "prefix",
                    {"type": "text", "text": "look"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}, "file_path": "/tmp/a.png"},
                ],
                "agent": "default",
            },
            {"role": "compress", "content": None},
        ],
    )

    messages = loop._build_messages(context)

    assert messages[0]["content"][0] == {"type": "text", "text": "prefix"}
    assert messages[0]["content"][2] == {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}
    assert messages[1] == {"role": "user", "content": ""}


def test_validate_tool_calls_keeps_assistant_when_tool_response_exists():
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "type": "function"}]},
        {"role": "tool", "content": "ok", "tool_call_id": "call_1"},
    ]

    validated = loop._validate_tool_calls(messages)

    assert "tool_calls" in validated[0]


@pytest.mark.asyncio
async def test_emit_retry_with_countdown_emits_retry_and_countdown_events():
    context = AgentContext(workspace=Path.cwd())
    events = []
    context.event_bus.subscribe(lambda event: events.append(event))

    await loop._emit_retry_with_countdown(
        context,
        message="retry",
        error_detail="boom",
        attempt=1,
        max_attempts=3,
        delay_seconds=2.2,
    )

    assert events[0].type == EventType.LLM_RETRY
    assert events[0].data["phase"] == "retrying"
    assert any(event.data.get("phase") == "countdown" for event in events[1:])


@pytest.mark.asyncio
async def test_run_agent_executes_tool_call_and_appends_tool_message(monkeypatch: pytest.MonkeyPatch):
    registry = ToolRegistry()

    @registry.register(
        name="echo_tool",
        description="echo",
        parameters={"type": "object", "properties": {"text": {"type": "string"}}},
    )
    async def echo_tool(text: str, context=None):
        return "X" * (loop._MAX_TOOL_RESULT_CHARS + 50)

    context = AgentContext(workspace=Path.cwd(), tool_registry=registry, model="gpt-4o", max_iterations=3)
    events = []
    context.event_bus.subscribe(lambda event: events.append(event))

    chunks = [
        _chunk(delta=_delta(tool_calls=[_tool_call("call_1", "echo_tool", '{"text": "hi"}')]), finish_reason=None),
        _chunk(delta=_delta(content="done"), finish_reason="stop", usage=_usage()),
    ]

    async def fake_acompletion(**kwargs):
        return _stream(chunks)

    async def fake_provider(provider_name=None):
        return SimpleNamespace(name="mock", provider_type="openai", api_key="k", base_url="", enabled=True)

    monkeypatch.setattr(loop, "_resolve_provider", fake_provider)
    monkeypatch.setattr(loop, "litellm", SimpleNamespace(acompletion=fake_acompletion, exceptions=loop.litellm.exceptions))
    monkeypatch.setattr("crabagent.core.proxy.resolve_llm_proxy", _async_return(""))

    messages = await loop.run_agent(context, "hello")

    assert any(msg.get("role") == "tool" for msg in messages)
    tool_msg = next(msg for msg in messages if msg.get("role") == "tool")
    assert "[truncated" in tool_msg["content"]
    assert any(event.type == EventType.TOOL_CALL for event in events)
    assert any(event.type == EventType.TOOL_RESULT for event in events)


@pytest.mark.asyncio
async def test_run_agent_reads_usage_after_finish_chunk(monkeypatch: pytest.MonkeyPatch):
    context = AgentContext(workspace=Path.cwd(), model="gpt-4o", max_iterations=2)

    async def fake_provider(provider_name=None):
        return SimpleNamespace(name="mock", provider_type="openai", api_key="k", base_url="", enabled=True)

    async def fake_acompletion(**kwargs):
        return _stream([
            _chunk(delta=_delta(content="done"), finish_reason="stop"),
            _usage_only_chunk(usage=_usage()),
        ])

    monkeypatch.setattr(loop, "_resolve_provider", fake_provider)
    monkeypatch.setattr(loop, "litellm", SimpleNamespace(acompletion=fake_acompletion, exceptions=loop.litellm.exceptions))
    monkeypatch.setattr("crabagent.core.proxy.resolve_llm_proxy", _async_return(""))

    messages = await loop.run_agent(context, "hello")

    assert messages[-1]["content"] == "done"
    assert context.total_tokens == 15
    assert context.visible_tokens == 14
    assert context.usage_records == [
        {
            "iteration": 1,
            "prompt_tokens": 10,
            "cached_tokens": 2,
            "non_cached_tokens": 8,
            "completion_tokens": 5,
            "reasoning_tokens": 1,
        }
    ]


@pytest.mark.asyncio
async def test_run_agent_emits_auth_error_and_stops(monkeypatch: pytest.MonkeyPatch):
    context = AgentContext(workspace=Path.cwd(), model="gpt-4o", max_iterations=1)
    events = []
    context.event_bus.subscribe(lambda event: events.append(event))

    async def fake_provider(provider_name=None):
        return SimpleNamespace(name="mock", provider_type="openai", api_key="k", base_url="", enabled=True)

    async def fake_acompletion(**kwargs):
        raise loop.litellm.exceptions.AuthenticationError(
            message="bad key",
            llm_provider="openai",
            model="gpt-4o",
        )

    monkeypatch.setattr(loop, "_resolve_provider", fake_provider)
    monkeypatch.setattr(loop, "litellm", SimpleNamespace(acompletion=fake_acompletion, exceptions=loop.litellm.exceptions))
    monkeypatch.setattr("crabagent.core.proxy.resolve_llm_proxy", _async_return(""))

    messages = await loop.run_agent(context, "hello")

    assert messages[0]["role"] == "user"
    assert any(event.type == EventType.AGENT_ERROR for event in events)
    error_event = next(event for event in events if event.type == EventType.AGENT_ERROR)
    assert "API 密钥" in error_event.data["error"]


@pytest.mark.asyncio
async def test_run_agent_emits_budget_exhausted_and_grace_call(monkeypatch: pytest.MonkeyPatch):
    context = AgentContext(workspace=Path.cwd(), model="gpt-4o", max_iterations=0)
    events = []
    context.event_bus.subscribe(lambda event: events.append(event))

    async def fake_grace(context_arg, llm, model):
        context_arg.messages.append({"role": "assistant", "content": "grace summary", "agent": context_arg.current_agent})

    monkeypatch.setattr(loop, "_grace_call", fake_grace)

    messages = await loop.run_agent(context, "hello")

    assert messages[0]["role"] == "user"
    assert messages[-1]["content"] == "grace summary"
    assert any(event.type == EventType.BUDGET_EXHAUSTED for event in events)


@pytest.mark.asyncio
async def test_run_agent_retries_context_window_with_compression(monkeypatch: pytest.MonkeyPatch):
    context = AgentContext(workspace=Path.cwd(), model="gpt-4o", max_iterations=3)
    events = []
    context.event_bus.subscribe(lambda event: events.append(event))
    calls = {"count": 0}

    async def fake_provider(provider_name=None):
        return SimpleNamespace(name="mock", provider_type="openai", api_key="k", base_url="", enabled=True)

    async def fake_acompletion(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise loop.litellm.exceptions.ContextWindowExceededError(
                message="too long",
                model="gpt-4o",
                llm_provider="openai",
            )
        return _stream([_chunk(delta=_delta(content="done"), finish_reason="stop", usage=_usage())])

    async def fake_compress(context_arg, llm_params, model_name):
        context_arg.metadata["compressed"] = model_name

    monkeypatch.setattr(loop, "_resolve_provider", fake_provider)
    monkeypatch.setattr(loop, "compress_context", fake_compress)
    monkeypatch.setattr(loop, "litellm", SimpleNamespace(acompletion=fake_acompletion, exceptions=loop.litellm.exceptions))
    monkeypatch.setattr("crabagent.core.proxy.resolve_llm_proxy", _async_return(""))

    messages = await loop.run_agent(context, "hello")

    assert calls["count"] == 2
    assert context.metadata["compressed"] == "openai/gpt-4o"
    assert messages[-1]["content"] == "done"
    assert any(event.type == EventType.AGENT_INFO and "自动压缩" in event.data["message"] for event in events)


class _Stream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        async def gen():
            for chunk in self._chunks:
                yield chunk

        return gen()


def _stream(chunks):
    return _Stream(chunks)


def _chunk(delta, finish_reason=None, usage=None):
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)], usage=usage)


def _usage_only_chunk(usage=None):
    return SimpleNamespace(choices=[], usage=usage)


def _delta(content=None, tool_calls=None, reasoning_content=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls, reasoning_content=reasoning_content)


def _tool_call(call_id: str, name: str, arguments: str, index: int = 0):
    return SimpleNamespace(id=call_id, index=index, function=SimpleNamespace(name=name, arguments=arguments))


def _usage():
    return SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=5,
        prompt_tokens_details=SimpleNamespace(cached_tokens=2),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=1),
    )


def _async_return(value):
    async def inner(*args, **kwargs):
        return value

    return inner

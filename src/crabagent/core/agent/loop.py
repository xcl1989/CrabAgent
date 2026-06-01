from __future__ import annotations

import asyncio
import json
import logging
import time

import litellm

from crabagent.core.agent.compress import compress_context
from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.token_limits import get_model_token_limit
from crabagent.core.config import settings
from crabagent.core.event import AgentEvent, EventType
from crabagent.core.provider_store import ProviderInfo, get_default_provider, get_provider

logger = logging.getLogger(__name__)


async def _resolve_provider(provider_name: str | None = None) -> ProviderInfo:
    if provider_name:
        info = await get_provider(provider_name)
        if info and info.enabled:
            return info
    info = await get_default_provider()
    if info:
        return info
    raise ValueError("No provider configured. Run 'crabagent provider add' to add one.")


def _litellm_params(provider: ProviderInfo) -> dict:
    params: dict = {"api_key": provider.api_key}
    if provider.base_url:
        params["api_base"] = provider.base_url
        params["custom_llm_provider"] = "openai"
    return params


_MAX_TOOL_RESULT_CHARS = 20_000


async def run_agent(
    context: AgentContext,
    query: str | list[dict],
) -> list[dict]:
    context.messages.append({"role": "user", "content": query, "agent": context.current_agent})

    provider = await _resolve_provider(context.provider_name)
    llm = _litellm_params(provider)
    model = context.model or "gpt-4"
    if "/" not in model:
        model = f"openai/{model}"
    context.metadata["resolved_model"] = model.split("/", 1)[-1] if "/" in model else model

    mcp_summary = [
        {"name": s["name"], "status": s["status"], "tool_count": s["tool_count"]}
        for s in context.metadata.get("mcp_status", [])
    ]
    await context.event_bus.emit(AgentEvent(type=EventType.AGENT_START, data={"mcp_servers": mcp_summary}))

    _stream_retries = 0
    _max_stream_retries = 2

    while not context.budget_exhausted:
        context.iteration += 1
        await context.event_bus.emit(AgentEvent(type=EventType.ITERATION_START, data={"iteration": context.iteration}))

        tools = context.tool_registry.tool_defs() or None

        max_context = get_model_token_limit(model)
        if context.total_tokens > max_context * settings.context_compression_threshold:
            await compress_context(context, llm, model)

        try:
            full_text = ""
            reasoning_text = ""
            tool_calls_list: list[dict] = []

            _llm_t0 = time.time()
            response = await litellm.acompletion(
                model=model,
                **llm,
                messages=_build_messages(context),
                tools=tools,
                max_tokens=settings.max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )

            finished = False
            async for chunk in response:
                if hasattr(chunk, "usage") and chunk.usage is not None:
                    usage = chunk.usage
                    context.total_tokens = (usage.prompt_tokens or 0) + (usage.completion_tokens or 0)

                if not chunk.choices:
                    if finished:
                        break
                    continue

                delta = chunk.choices[0].delta

                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    reasoning_text += delta.reasoning_content
                    await context.event_bus.emit(
                        AgentEvent(type=EventType.THINKING_DELTA, data={"text": delta.reasoning_content})
                    )

                if delta.content:
                    full_text += delta.content
                    await context.event_bus.emit(AgentEvent(type=EventType.TEXT_DELTA, data={"text": delta.content}))

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = getattr(tc, "index", None) or 0
                        if tc.function.name and tc.id:
                            tool_calls_list.append(
                                {
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments or "",
                                    },
                                }
                            )
                        elif tool_calls_list and tc.function.arguments is not None:
                            if idx < len(tool_calls_list):
                                tool_calls_list[idx]["function"]["arguments"] += tc.function.arguments
                            else:
                                tool_calls_list[-1]["function"]["arguments"] += tc.function.arguments

                if chunk.choices[0].finish_reason:
                    finished = True

            assistant_msg: dict = {
                "role": "assistant",
                "content": full_text or "",
            }

            _llm_elapsed = time.time() - _llm_t0
            if _llm_elapsed > 10:
                logger.debug("litellm call took %.1fs", _llm_elapsed)

            if tool_calls_list:
                assistant_msg["tool_calls"] = tool_calls_list
            if reasoning_text:
                assistant_msg["reasoning_content"] = reasoning_text

            assistant_msg["agent"] = context.current_agent

            if reasoning_text:
                await context.event_bus.emit(AgentEvent(type=EventType.THINKING_DONE, data={"text": reasoning_text}))

            context.messages.append(assistant_msg)

            await context.event_bus.emit(AgentEvent(type=EventType.MESSAGE_CREATED, data={"message": assistant_msg}))

            await context.event_bus.emit(AgentEvent(type=EventType.TEXT_DONE, data={"text": full_text}))

            if not tool_calls_list:
                break

            tool_metas = []
            for tc in tool_calls_list:
                func = tc["function"]
                tool_name = func["name"]
                try:
                    args = json.loads(func["arguments"])
                except json.JSONDecodeError:
                    args = {}
                tool_info = context.tool_registry.get(tool_name)
                tool_source = tool_info.metadata.get("source", "builtin") if tool_info else "builtin"
                tool_server = tool_info.metadata.get("server_name", "") if tool_info else ""
                tool_metas.append(
                    {
                        "tc": tc,
                        "name": tool_name,
                        "args": args,
                        "source": tool_source,
                        "server": tool_server,
                    }
                )

            for meta in tool_metas:
                await context.event_bus.emit(
                    AgentEvent(
                        type=EventType.TOOL_CALL,
                        data={
                            "name": meta["name"],
                            "arguments": meta["args"],
                            "id": meta["tc"]["id"],
                            "source": meta["source"],
                            "server_name": meta["server"],
                        },
                    )
                )

            async def _run_and_emit(meta: dict):
                result = await context.tool_registry.execute(meta["name"], meta["args"], context=context)
                await context.event_bus.emit(
                    AgentEvent(
                        type=EventType.TOOL_RESULT,
                        data={
                            "name": meta["name"],
                            "result": result[:2000],
                            "id": meta["tc"]["id"],
                            "source": meta["source"],
                            "server_name": meta["server"],
                        },
                    )
                )
                return meta, result

            gathered = await asyncio.gather(*[_run_and_emit(m) for m in tool_metas])

            for meta, result in gathered:
                orig_len = len(result)
                if orig_len > _MAX_TOOL_RESULT_CHARS:
                    result = result[:_MAX_TOOL_RESULT_CHARS] + (
                        f"\n\n... [truncated {orig_len - _MAX_TOOL_RESULT_CHARS} chars]"
                    )
                tool_msg = {
                    "role": "tool",
                    "content": result,
                    "tool_call_id": meta["tc"]["id"],
                    "agent": context.current_agent,
                }
                context.messages.append(tool_msg)

                await context.event_bus.emit(AgentEvent(type=EventType.MESSAGE_CREATED, data={"message": tool_msg}))

            for msg in context.metadata.pop("_pending_sub_agent_messages", []):
                await context.event_bus.emit(AgentEvent(type=EventType.MESSAGE_CREATED, data={"message": msg}))

            await context.event_bus.emit(
                AgentEvent(type=EventType.ITERATION_END, data={"iteration": context.iteration})
            )

        except Exception as e:
            err_name = type(e).__name__
            if _stream_retries < _max_stream_retries and "MidStreamFallback" in err_name:
                _stream_retries += 1
                logger.warning("Stream error (retry %d/%d): %s", _stream_retries, _max_stream_retries, e)
                continue
            logger.error(f"Agent loop error: {e}", exc_info=True)
            await context.event_bus.emit(AgentEvent(type=EventType.AGENT_ERROR, data={"error": str(e)}))
            break

    if context.budget_exhausted:
        await context.event_bus.emit(
            AgentEvent(type=EventType.BUDGET_EXHAUSTED, data={"iterations": context.iteration})
        )
        await _grace_call(context, llm, model)

    return context.messages


async def _grace_call(context: AgentContext, llm: dict, model: str):
    try:
        _g0 = time.time()
        context.messages.append(
            {
                "role": "user",
                "content": (
                    "You have exhausted your iteration budget. "
                    "Please summarize what you've done and any remaining steps."
                ),
                "agent": context.current_agent,
            }
        )
        response = await litellm.acompletion(
            model=model,
            **llm,
            messages=_build_messages(context),
            max_tokens=1024,
        )
        content = response.choices[0].message.content or ""
        _gelapsed = time.time() - _g0
        if _gelapsed > 5:
            logger.info("_grace_call took %.1fs", _gelapsed)
        context.messages.append({"role": "assistant", "content": content, "agent": context.current_agent})
        await context.event_bus.emit(AgentEvent(type=EventType.TEXT_DONE, data={"text": content}))
    except Exception as e:
        logger.error(f"Grace call failed: {e}")


def _build_messages(context: AgentContext) -> list[dict]:
    from crabagent.core.agent.token_limits import is_vision_model

    vision = is_vision_model(context.model or "")
    messages = []
    if context.system_prompt:
        messages.append({"role": "system", "content": context.system_prompt})
    for msg in context.messages:
        content = msg.get("content")
        if isinstance(content, list):
            if vision:
                clean_blocks = []
                for block in content:
                    if not isinstance(block, dict):
                        if isinstance(block, str):
                            clean_blocks.append({"type": "text", "text": block})
                        continue
                    if block.get("type") == "text":
                        clean_blocks.append({"type": "text", "text": block.get("text", "")})
                    elif block.get("type") == "image_url":
                        clean_blocks.append({"type": "image_url", "image_url": {"url": block["image_url"]["url"]}})
                messages.append({**msg, "content": clean_blocks})
            else:
                text_parts = []
                for block in content:
                    if not isinstance(block, dict):
                        if isinstance(block, str):
                            text_parts.append(block)
                        continue
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "image_url":
                        file_path = block.get("file_path", "")
                        mime = block.get("mime", "")
                        size_kb = block.get("size_kb", 0)
                        if file_path:
                            text_parts.append(f"\n[Attached image: {file_path} ({mime}, {size_kb}KB)]")
                        elif mime:
                            text_parts.append(f"\n[Attached image: {mime}, {size_kb}KB]")
                text = "".join(text_parts)
                messages.append({**msg, "content": text})
            continue
        if content is None:
            msg = dict(msg, content="")
        elif msg.get("role") == "assistant" and not content and not msg.get("tool_calls"):
            msg = dict(msg, content="")
        messages.append(msg)
    return messages

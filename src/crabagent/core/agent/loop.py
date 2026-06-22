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


def _litellm_params(provider: ProviderInfo, proxy: str = "") -> dict:
    # ChatGPT subscription provider uses litellm's built-in OAuth flow.
    # No api_key / api_base needed — litellm's ChatGPTConfig handles everything.
    if provider.provider_type == "chatgpt":
        return {}
    params: dict = {"api_key": provider.api_key}
    if provider.base_url:
        params["api_base"] = provider.base_url
        params["custom_llm_provider"] = "openai"
    if proxy:
        params["proxy"] = proxy
    return params


_MAX_TOOL_RESULT_CHARS = 20_000


def _preview_result(result: object, max_chars: int = 2000) -> str:
    """Render a short string preview of a tool result for SSE events."""
    if isinstance(result, str):
        return result[:max_chars]
    if isinstance(result, list):
        parts: list[str] = []
        total = 0
        for block in result:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "image_url":
                    url = block.get("image_url", {}).get("url", "")
                    if url.startswith("data:"):
                        parts.append("[image embedded]")
                    else:
                        parts.append(f"[image: {url[:80]}]")
            else:
                parts.append(str(block))
            total += len(parts[-1])
            if total >= max_chars:
                break
        text = "\n".join(parts)
        return text[:max_chars]
    return str(result)[:max_chars]


def _truncate_result(result: object, max_chars: int) -> object:
    """Truncate a string result; pass list (multimodal) results through."""
    if isinstance(result, str):
        orig_len = len(result)
        if orig_len > max_chars:
            return result[:max_chars] + (f"\n\n... [truncated {orig_len - max_chars} chars]")
        return result
    if isinstance(result, list):
        # Truncate any text blocks; leave image_url blocks untouched
        out: list = []
        for block in result:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if len(text) > max_chars:
                    block = {**block, "text": text[:max_chars] + "\n\n... [truncated]"}
            out.append(block)
        return out
    return result


async def _emit_retry_with_countdown(
    context: AgentContext,
    message: str,
    error_detail: str,
    attempt: int,
    max_attempts: int,
    delay_seconds: float,
) -> None:
    """Emit LLM_RETRY events: one initial announcement, then countdown ticks."""
    # Initial announcement
    await context.event_bus.emit(
        AgentEvent(
            type=EventType.LLM_RETRY,
            data={
                "phase": "retrying",
                "message": message,
                "error_detail": error_detail,
                "attempt": attempt,
                "max_attempts": max_attempts,
                "delay_seconds": delay_seconds,
            },
        )
    )

    # Emit countdown ticks at 1-second intervals (only for delays >= 2s)
    remaining = int(delay_seconds)
    while remaining > 1:
        await asyncio.sleep(1)
        remaining -= 1
        await context.event_bus.emit(
            AgentEvent(
                type=EventType.LLM_RETRY,
                data={
                    "phase": "countdown",
                    "message": message,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "remaining_seconds": remaining,
                },
            )
        )

    # Sleep the remaining fractional second
    frac = delay_seconds - int(delay_seconds)
    if frac > 0:
        await asyncio.sleep(frac)


async def run_agent(
    context: AgentContext,
    query: str | list[dict],
) -> list[dict]:
    _t0 = time.time()
    context.messages.append({"role": "user", "content": query, "agent": context.current_agent})
    context.metadata["_batch_molt"] = True  # batch molts per round

    # Fire middleware start hooks (reflect / title / compress etc.)
    if context.middlewares:
        try:
            await context.middlewares.run_start(context)
        except Exception:
            logger.debug("middleware run_start failed", exc_info=True)

    provider = await _resolve_provider(context.provider_name)
    from crabagent.core.proxy import resolve_llm_proxy

    proxy = await resolve_llm_proxy(provider)
    llm = _litellm_params(provider, proxy)
    model = context.model or "gpt-4"
    if "/" not in model:
        # ChatGPT subscription provider uses litellm's built-in chatgpt/ prefix
        if provider.provider_type == "chatgpt":
            model = f"chatgpt/{model}"
        else:
            model = f"openai/{model}"

    # For chatgpt provider, verify OAuth token exists before calling litellm
    # (litellm would otherwise block trying interactive device code login)
    if provider.provider_type == "chatgpt":
        import os
        token_file = os.path.join(
            os.getenv("CHATGPT_TOKEN_DIR", os.path.expanduser("~/.config/litellm/chatgpt")),
            os.getenv("CHATGPT_AUTH_FILE", "auth.json"),
        )
        if not os.path.exists(token_file):
            raise ValueError(
                "ChatGPT subscription not logged in. "
                "Please go to Settings → Providers → ChatGPT → Login to authorize first."
            )
    context.metadata["resolved_model"] = model.split("/", 1)[-1] if "/" in model else model
    context.metadata["resolved_provider"] = provider.name

    mcp_summary = [
        {"name": s["name"], "status": s["status"], "tool_count": s["tool_count"]}
        for s in context.metadata.get("mcp_status", [])
    ]
    await context.event_bus.emit(AgentEvent(type=EventType.AGENT_START, data={"mcp_servers": mcp_summary}))

    _stream_retries = 0
    _max_stream_retries = 2
    _llm_retry_count = 0
    _llm_retry_max = settings.llm_retry_max
    context.metadata["_llm_params"] = dict(llm)
    context.metadata["_resolved_model"] = model.split("/", 1)[-1] if "/" in model else model

    while not context.budget_exhausted:
        context.iteration += 1
        await context.event_bus.emit(AgentEvent(type=EventType.ITERATION_START, data={"iteration": context.iteration}))

        locale = context.metadata.get("locale", context.locale)
        tools = context.tool_registry.tool_defs(locale=locale) or None

        try:
            full_text = ""
            reasoning_text = ""
            tool_calls_list: list[dict] = []

            _llm_t0 = time.time()
            reasoning_effort = context.metadata.get("reasoning_effort", settings.reasoning_effort)
            response = await litellm.acompletion(
                model=model,
                **llm,
                messages=_build_messages(context),
                tools=tools,
                **({} if provider.provider_type == "chatgpt" else {"max_tokens": settings.max_tokens}),
                stream=True,
                stream_options={"include_usage": True},
                reasoning_effort=reasoning_effort,
                allowed_openai_params=["reasoning_effort"],
            )

            finished = False
            async for chunk in response:
                if hasattr(chunk, "usage") and chunk.usage is not None:
                    usage = chunk.usage
                    prompt_tokens = usage.prompt_tokens or 0
                    completion_tokens = usage.completion_tokens or 0

                    # ── Extract cached tokens from prompt_tokens_details ──
                    cached_tokens = 0
                    if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
                        cached_tokens = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
                    non_cached_tokens = prompt_tokens - cached_tokens

                    # ── Extract reasoning tokens (existing logic) ──
                    reasoning_tokens = 0
                    if hasattr(usage, "completion_tokens_details") and usage.completion_tokens_details:
                        reasoning_tokens = usage.completion_tokens_details.reasoning_tokens or 0

                    context.total_tokens = prompt_tokens + completion_tokens
                    context.visible_tokens = context.total_tokens - reasoning_tokens

                    # ── Accumulate across all iterations in this run ──
                    context.accumulated_prompt += prompt_tokens
                    context.accumulated_completion += completion_tokens
                    context.accumulated_cached += cached_tokens
                    context.accumulated_reasoning += reasoning_tokens

                    # ── Per-iteration record for DB persistence ──
                    context.usage_records.append({
                        "iteration": context.iteration,
                        "prompt_tokens": prompt_tokens,
                        "cached_tokens": cached_tokens,
                        "non_cached_tokens": non_cached_tokens,
                        "completion_tokens": completion_tokens,
                        "reasoning_tokens": reasoning_tokens,
                    })

                    logger.info(
                        "LLM usage: prompt=%d (cached=%d, fresh=%d) completion=%d (reasoning=%d) iter=%d model=%s",
                        prompt_tokens,
                        cached_tokens,
                        non_cached_tokens,
                        completion_tokens,
                        reasoning_tokens,
                        context.iteration,
                        model,
                    )

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
                            idx = getattr(tc, "index", None)
                            if idx is not None and 0 <= idx < len(tool_calls_list):
                                target = idx
                            else:
                                target = len(tool_calls_list) - 1
                            tool_calls_list[target]["function"]["arguments"] += tc.function.arguments

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
            elif reasoning_tokens > 0:
                # ChatGPT subscription returns encrypted reasoning (no plaintext).
                # Emit a placeholder so the user sees that thinking happened.
                placeholder = f"🧠 模型使用了 {reasoning_tokens} tokens 进行推理（内容已加密，不公开）"
                assistant_msg["reasoning_content"] = placeholder
                await context.event_bus.emit(AgentEvent(type=EventType.THINKING_DONE, data={"text": placeholder}))

            # Context compression: check AFTER LLM returns (we now have the
            # real token count) but BEFORE appending the current response,
            # so compression doesn't need to deal with messages from the
            # current iteration — simplifying DB persistence.
            max_context = get_model_token_limit(model)
            if context.total_tokens > max_context * settings.context_compression_threshold:
                if context.middlewares:
                    try:
                        await context.middlewares.run_before_llm(context, context.messages)
                    except Exception:
                        logger.debug("middleware before_llm failed", exc_info=True)
                else:
                    await compress_context(context, llm, model)

            context.messages.append(assistant_msg)

            # Reset retry counters on success
            _llm_retry_count = 0
            _stream_retries = 0

            await context.event_bus.emit(AgentEvent(type=EventType.MESSAGE_CREATED, data={"message": assistant_msg}))

            await context.event_bus.emit(AgentEvent(type=EventType.TEXT_DONE, data={"text": full_text}))

            if not tool_calls_list:
                break

            tool_metas = []
            for tc in tool_calls_list:
                func = tc["function"]
                tool_name = func["name"]
                raw_args = func["arguments"]
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    logger.warning(
                        "Tool '%s' arguments JSON parse failed (len=%d): %.200s",
                        tool_name,
                        len(raw_args),
                        raw_args,
                    )
                    hint = (
                        f"Error: tool '{tool_name}' arguments were truncated by max_tokens "
                        f"(raw length={len(raw_args)}). The JSON is incomplete and cannot be parsed. "
                        f"Reduce the content size or break it into smaller writes, then retry."
                    )
                    args = {"_truncated_error": hint}
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
                preview = _preview_result(result)
                await context.event_bus.emit(
                    AgentEvent(
                        type=EventType.TOOL_RESULT,
                        data={
                            "name": meta["name"],
                            "result": preview,
                            "id": meta["tc"]["id"],
                            "source": meta["source"],
                            "server_name": meta["server"],
                        },
                    )
                )
                return meta, result

            gathered = await asyncio.gather(*[_run_and_emit(m) for m in tool_metas], return_exceptions=True)

            for i in range(len(tool_metas)):
                result_entry = gathered[i]
                meta = tool_metas[i]
                tc = meta["tc"]
                if isinstance(result_entry, Exception):
                    result = f"Tool error: {result_entry}"
                    await context.event_bus.emit(
                        AgentEvent(
                            type=EventType.TOOL_RESULT,
                            data={
                                "name": meta["name"],
                                "result": result[:2000],
                                "id": tc["id"],
                                "source": meta["source"],
                                "server_name": meta["server"],
                            },
                        )
                    )
                else:
                    meta, result = result_entry
                    result = _truncate_result(result, _MAX_TOOL_RESULT_CHARS)
                tool_msg = {
                    "role": "tool",
                    "content": result,
                    "tool_call_id": tc["id"],
                    "agent": context.current_agent,
                    "name": meta["name"],
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

            # ── Stream mid-point errors (partial response received then cut) ──
            _stream_errors = (
                "MidStreamFallback",
                "RemoteProtocolError",
                "ReadError",
                "IncompleteReadError",
            )
            if any(s in err_name for s in _stream_errors) and _stream_retries < _max_stream_retries:
                _stream_retries += 1
                stream_delay = 1.0 * _stream_retries
                logger.warning("Stream error (retry %d/%d): %s", _stream_retries, _max_stream_retries, e)
                await context.event_bus.emit(
                    AgentEvent(
                        type=EventType.LLM_RETRY,
                        data={
                            "reason": "stream_error",
                            "message": f"🔄 流式连接中断（{err_name}）",
                            "attempt": _stream_retries,
                            "max_attempts": _max_stream_retries,
                            "delay_seconds": stream_delay,
                            "phase": "retrying",
                        },
                    )
                )
                await asyncio.sleep(stream_delay)
                continue

            # ── Determine retry strategy ──
            retryable = False
            user_message = ""
            backoff_delay = 0.0

            if isinstance(e, litellm.exceptions.RateLimitError):
                retryable = True
                backoff_delay = min(
                    settings.llm_retry_base_delay * (2 ** _llm_retry_count),
                    settings.llm_retry_max_delay,
                )
                user_message = "⚠️ API 速率已达上限"

            elif isinstance(e, (litellm.exceptions.Timeout, asyncio.TimeoutError)):
                retryable = True
                backoff_delay = min(
                    settings.llm_retry_base_delay * (1.5 ** _llm_retry_count),
                    settings.llm_retry_max_delay,
                )
                user_message = "⏱️ API 请求超时"

            elif isinstance(e, litellm.exceptions.APIConnectionError):
                retryable = True
                backoff_delay = min(
                    settings.llm_retry_base_delay * (2 ** _llm_retry_count),
                    settings.llm_retry_max_delay,
                )
                user_message = "🔌 网络连接失败"

            elif isinstance(e, (litellm.exceptions.ServiceUnavailableError, litellm.exceptions.InternalServerError)):
                retryable = True
                backoff_delay = min(
                    settings.llm_retry_base_delay * (2 ** _llm_retry_count),
                    settings.llm_retry_max_delay,
                )
                user_message = f"⚠️ API 服务暂时不可用（{err_name}）"

            elif isinstance(e, (ConnectionError, OSError)):
                retryable = True
                backoff_delay = min(
                    settings.llm_retry_base_delay * (2 ** _llm_retry_count),
                    settings.llm_retry_max_delay,
                )
                user_message = "🔌 网络异常"

            elif isinstance(e, litellm.exceptions.ContextWindowExceededError):
                # Attempt auto-compression then retry
                await context.event_bus.emit(
                    AgentEvent(type=EventType.AGENT_INFO, data={"message": "📏 上下文超出模型限制，正在尝试自动压缩…"})
                )
                try:
                    await compress_context(context, llm, model)
                    _llm_retry_count = 0  # reset since context changed
                    logger.info("Context auto-compressed after ContextWindowExceededError, retrying")
                    await context.event_bus.emit(
                        AgentEvent(type=EventType.AGENT_INFO, data={"message": "✅ 上下文压缩成功，自动重试中…"})
                    )
                    continue
                except Exception:
                    user_message = "📏 上下文超出模型限制，自动压缩失败。请新建对话或缩短内容后重试。"
                    logger.warning("Auto-compression also failed after ContextWindowExceededError")

            elif isinstance(e, litellm.exceptions.AuthenticationError):
                user_message = "🔑 API 密钥无效或已过期，请在「设置」中更新 Provider 配置。"
                logger.error("AuthenticationError - invalid or expired API key")

            elif isinstance(e, litellm.exceptions.BudgetExceededError):
                user_message = "💰 API 预算已耗尽，请在 Provider 后台充值或切换模型。"

            elif isinstance(e, litellm.exceptions.ContentPolicyViolationError):
                user_message = "🚫 内容被安全策略拦截，请修改输入后重试。"

            elif isinstance(e, litellm.exceptions.BadRequestError):
                user_message = f"❌ 请求参数错误：{e!s}"
                logger.warning("BadRequestError details: %s", e)

            else:
                # Generic / unknown error — still retry once for safety
                retryable = True
                backoff_delay = settings.llm_retry_base_delay
                user_message = f"❌ LLM 调用异常（{err_name}）"

            # ── Retry if recoverable and under limit ──
            if retryable and _llm_retry_count < _llm_retry_max:
                _llm_retry_count += 1

                # Emit countdown ticks for user visibility
                await _emit_retry_with_countdown(
                    context,
                    message=user_message,
                    error_detail=str(e)[:200],
                    attempt=_llm_retry_count,
                    max_attempts=_llm_retry_max,
                    delay_seconds=backoff_delay,
                )

                logger.warning(
                    "%s (retry %d/%d, delay=%.1fs): %s",
                    err_name, _llm_retry_count, _llm_retry_max, backoff_delay, e,
                )
                await asyncio.sleep(backoff_delay)
                continue

            # ── Non-recoverable or retries exhausted ──
            final_msg = user_message
            if retryable and _llm_retry_count >= _llm_retry_max:
                final_msg += f"（已重试 {_llm_retry_max} 次仍失败）"

            logger.error(f"Agent loop error (final): {e}", exc_info=True)
            await context.event_bus.emit(
                AgentEvent(
                    type=EventType.LLM_RETRY,
                    data={
                        "phase": "exhausted",
                        "message": final_msg,
                        "attempt": _llm_retry_count,
                        "max_attempts": _llm_retry_max,
                    },
                )
            )
            await context.event_bus.emit(
                AgentEvent(type=EventType.AGENT_ERROR, data={"error": final_msg})
            )
            break

    if context.budget_exhausted:
        await context.event_bus.emit(
            AgentEvent(type=EventType.BUDGET_EXHAUSTED, data={"iterations": context.iteration})
        )
        await _grace_call(context, llm, model)

    # Fire middleware end hooks (reflect / title / etc.)
    context.metadata["_run_elapsed"] = round(time.time() - _t0, 1)
    if context.middlewares:
        try:
            await context.middlewares.run_end(context)
        except Exception:
            logger.debug("middleware run_end failed", exc_info=True)

    # Flush pending molts into a single snapshot per round
    try:
        registry = context.tool_registry
        if hasattr(registry, "_flush_molt_snapshot"):
            await registry._flush_molt_snapshot(context)
    except Exception:
        logger.debug("molt flush failed", exc_info=True)

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
        if msg.get("role") not in ("system", "user", "assistant", "tool"):
            # compress / agent_switch etc. → user for LLM
            msg = {**msg, "role": "user"}
        messages.append(msg)

    # Strip internal-only fields (e.g. "agent") before sending to LLM API.
    # Some providers (e.g. Kimi) reject extra fields with strict validation.
    _VALID_KEYS: dict[str, set[str]] = {
        "system": {"role", "content"},
        "user": {"role", "content"},
        "assistant": {"role", "content", "tool_calls", "reasoning_content"},
        "tool": {"role", "content", "tool_call_id"},
    }
    cleaned = []
    for msg in messages:
        role = msg.get("role", "")
        valid = _VALID_KEYS.get(role, {"role", "content"})
        cleaned.append({k: v for k, v in msg.items() if k in valid})

    return _validate_tool_calls(cleaned)


def _validate_tool_calls(messages: list[dict]) -> list[dict]:
    """Strip tool_calls from assistant messages that lack corresponding tool responses.

    Protects against corrupted history where assistant tool_calls were saved to DB
    but the corresponding tool messages were not (e.g. due to a prior crash/error).
    """
    for i, msg in enumerate(messages):
        tool_calls = msg.get("tool_calls")
        if msg.get("role") != "assistant" or not tool_calls:
            continue
        required_ids = {tc["id"] for tc in tool_calls if tc.get("id")}
        if not required_ids:
            continue
        found_ids = set()
        for later_msg in messages[i + 1 :]:
            if later_msg.get("role") == "tool":
                found_ids.add(later_msg.get("tool_call_id", ""))
        missing = required_ids - found_ids
        if missing:
            logger.warning("Stripping %d orphan tool_calls from assistant (missing: %s)", len(missing), missing)
            messages[i] = {k: v for k, v in msg.items() if k != "tool_calls"}
    return messages

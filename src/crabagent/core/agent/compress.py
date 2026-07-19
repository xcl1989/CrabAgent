from __future__ import annotations

import asyncio
import logging

import litellm

from crabagent.core.agent.context import AgentContext
from crabagent.core.config import settings
from crabagent.core.event import AgentEvent, EventType
from crabagent.core.i18n import t

logger = logging.getLogger(__name__)

_MAX_SUMMARY_TOOL_RESULT_CHARS = 12_000


async def summarize_messages(
    messages: list[dict],
    *,
    system_prompt: str,
    llm_params: dict,
    model: str,
    locale: str = "en",
    on_delta=None,
) -> str:
    """Summarize messages using the same prompt and sanitizing as auto-compression."""
    early = messages

    # --- Build the compression request using original messages ---
    # Key insight: we send the EXACT same system prompt + conversation
    # messages as a normal LLM call (not a formatted text blob), so the
    # provider can reuse prompt-cached tokens to the fullest extent.
    # Only the final instruction message is "fresh" content.
    #
    # We do NOT replace the system prompt — doing so would bust the
    # entire prefix cache and make compression as expensive as a full
    # regeneration.

    compress_instruction = t("compress.instruction", locale)

    # Build messages: original system prompt + all early messages (as-is)
    compress_messages: list[dict] = []

    if system_prompt:
        compress_messages.append({"role": "system", "content": system_prompt})

    # Tool-call objects are provider wire protocol, not conversation content.
    # Passing them without the original `tools` definitions causes some providers
    # to echo them as DSML/XML instead of producing a useful summary.
    tool_names: dict[str, str] = {}
    for msg in early:
        if msg.get("role") != "assistant":
            continue
        for tool_call in msg.get("tool_calls") or []:
            if not isinstance(tool_call, dict):
                continue
            tool_id = tool_call.get("id")
            function = tool_call.get("function") or {}
            if tool_id:
                tool_names[tool_id] = function.get("name") or "unknown"

    for msg in early:
        # Skip internal placeholders that carry no information.
        if msg.get("_compress_ack") or msg.get("role") in ("stats", "screenshot"):
            continue

        content = msg.get("content", "")
        # Handle list content (e.g. image blocks) — strip to text only.
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    text_parts.append(block)
            content = " ".join(text_parts)
        elif isinstance(content, str) and "data:image" in content:
            # Strip embedded base64 image data from string content.
            import re
            content = re.sub(
                r'data:image/[^;]+;base64,[A-Za-z0-9+/=]{100,}',
                '[image omitted]',
                content,
            )

        role = msg.get("role", "user")
        if role == "assistant" and msg.get("tool_calls"):
            names = [
                (tool_call.get("function") or {}).get("name", "unknown")
                for tool_call in msg["tool_calls"]
                if isinstance(tool_call, dict)
            ]
            call_note = f"[Tool call: {', '.join(names)}]"
            content = f"{content}\n{call_note}".strip()
        elif role == "tool":
            # Convert the result into ordinary text. This preserves the useful
            # outcome while removing the strict tool-call/result API sequence.
            name = tool_names.get(msg.get("tool_call_id"), msg.get("name") or "unknown")
            if len(content) > _MAX_SUMMARY_TOOL_RESULT_CHARS:
                omitted = len(content) - _MAX_SUMMARY_TOOL_RESULT_CHARS
                content = f"{content[:_MAX_SUMMARY_TOOL_RESULT_CHARS]}\n[... {omitted} characters omitted]"
            content = f"[Tool result: {name}]\n{content}".strip()
            role = "user"
        elif role not in ("user", "assistant"):
            role = "user"

        if content:
            compress_messages.append({"role": role, "content": content})

    # Final instruction — this is the only truly "fresh" content
    compress_messages.append({"role": "user", "content": compress_instruction})

    last_exc: Exception | None = None
    for attempt in range(settings.llm_retry_max + 1):
        try:
            response = await litellm.acompletion(
                model=model,
                **llm_params,
                messages=compress_messages,
                max_tokens=8192,
                stream=True,
                stream_options={"include_usage": True},
            )

            content_buf = ""
            reasoning_buf = ""
            async for chunk in response:
                if not chunk.choices:
                    # Capture usage for logging
                    if hasattr(chunk, "usage") and chunk.usage:
                        prompt_t = getattr(chunk.usage, "prompt_tokens", 0) or 0
                        cached_t = 0
                        if hasattr(chunk.usage, "prompt_tokens_details") and chunk.usage.prompt_tokens_details:
                            cached_t = getattr(chunk.usage.prompt_tokens_details, "cached_tokens", 0) or 0
                        fresh_t = prompt_t - cached_t
                        logger.info(
                            "Compress usage: prompt=%d (cached=%d, fresh=%d) — %s cache hit",
                            prompt_t, cached_t, fresh_t,
                            f"{cached_t / prompt_t * 100:.0f}%" if prompt_t else "N/A",
                        )
                    continue
                delta = chunk.choices[0].delta
                piece = ""
                if delta.content:
                    piece = delta.content
                    content_buf += piece
                elif hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    reasoning_buf += delta.reasoning_content

                if piece and on_delta:
                    result = on_delta(piece)
                    if hasattr(result, "__await__"):
                        await result

            # Prefer actual content; fall back to reasoning only if content is empty
            summary = content_buf.strip() or reasoning_buf.strip()
            last_exc = None
            break  # success
        except (litellm.exceptions.RateLimitError, litellm.exceptions.Timeout,
                litellm.exceptions.APIConnectionError, litellm.exceptions.ServiceUnavailableError,
                litellm.exceptions.InternalServerError) as exc:
            last_exc = exc
            delay = min(settings.llm_retry_base_delay * (2 ** attempt), settings.llm_retry_max_delay)
            logger.warning(
                "Compress LLM call failed (attempt %d/%d): %s, retrying in %.1fs",
                attempt + 1, settings.llm_retry_max + 1, exc, delay,
            )
            await asyncio.sleep(delay)
        except Exception as exc:
            last_exc = exc
            break  # non-retryable error

    if last_exc is not None:
        raise RuntimeError(f"Context compression failed: {last_exc}") from last_exc
    return summary


async def compress_context(context: AgentContext, llm_params: dict, model: str) -> None:
    keep = settings.context_keep_recent
    messages = context.messages
    if len(messages) <= keep + 2:
        return

    early = messages[:-keep]
    recent = messages[-keep:]
    locale = context.metadata.get("locale", context.locale or "en")

    await context.event_bus.emit(
        AgentEvent(type=EventType.COMPRESS_START, data={"original_count": len(messages)})
    )

    async def emit_delta(piece: str) -> None:
        await context.event_bus.emit(AgentEvent(type=EventType.COMPRESS_DELTA, data={"text": piece}))

    try:
        summary = await summarize_messages(
            early,
            system_prompt=context.system_prompt,
            llm_params=llm_params,
            model=model,
            locale=locale,
            on_delta=emit_delta,
        )
    except Exception:
        logger.warning("Context compression failed, keeping original", exc_info=True)
        await context.event_bus.emit(
            AgentEvent(type=EventType.CONTEXT_COMPRESSED, data={
                "original_count": len(messages), "compressed_count": len(messages),
                "summary_length": 0, "failed": True,
            })
        )
        return

    compressed = [
        {
            "role": "compress",
            "content": summary,
        },
        {
            "role": "assistant",
            "content": "Understood. I will continue based on this context summary.",
            "_compress_ack": True,
        },
    ]

    context.messages = compressed + recent
    context.total_tokens = 0
    context.visible_tokens = 0

    # Inline DB persistence: mark all existing DB messages as compressed
    # and insert the summary now, so that subsequent PersistenceListener
    # saves (current iteration's assistant/tool) get higher ids naturally.
    persistence = context.metadata.get("_persistence")
    if persistence:
        try:
            await persistence.persist_compression(summary, preserve_recent=len(recent))
        except Exception:
            logger.exception("Failed to persist compression to DB")

    await context.event_bus.emit(
        AgentEvent(
            type=EventType.CONTEXT_COMPRESSED,
            data={
                "original_count": len(early) + keep,
                "compressed_count": len(context.messages),
                "summary_length": len(summary),
            },
        )
    )
    logger.info(
        "Context compressed: %d -> %d messages (summary: %d chars)",
        len(early) + keep,
        len(context.messages),
        len(summary),
    )

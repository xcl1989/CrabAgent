from __future__ import annotations

import asyncio
import logging

import litellm

from crabagent.core.agent.context import AgentContext
from crabagent.core.config import settings
from crabagent.core.event import AgentEvent, EventType
from crabagent.core.i18n import t

logger = logging.getLogger(__name__)


async def compress_context(context: AgentContext, llm_params: dict, model: str) -> None:
    keep = settings.context_keep_recent
    messages = context.messages

    if len(messages) <= keep + 2:
        return

    early = messages[:-keep]
    recent = messages[-keep:]

    locale = context.metadata.get("locale", context.locale or "en")

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

    if context.system_prompt:
        compress_messages.append({"role": "system", "content": context.system_prompt})

    for msg in early:
        # Skip internal placeholders that carry no information
        if msg.get("_compress_ack"):
            continue
        if msg.get("role") in ("stats", "screenshot"):
            continue
        # Normalise internal roles to valid LLM roles
        role = msg.get("role", "user")
        if role not in ("user", "assistant", "tool"):
            role = "user"
        content = msg.get("content", "")
        # Handle list content (e.g. image blocks) — strip to text
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    text_parts.append(block)
            content = " ".join(text_parts)
        if not content and not msg.get("tool_calls"):
            continue
        clean_msg: dict = {"role": role, "content": content or ""}
        # Preserve tool_calls / tool_call_id for valid sequences
        if msg.get("tool_calls"):
            clean_msg["tool_calls"] = msg["tool_calls"]
        if msg.get("tool_call_id"):
            clean_msg["tool_call_id"] = msg["tool_call_id"]
        compress_messages.append(clean_msg)

    # Final instruction — this is the only truly "fresh" content
    compress_messages.append({"role": "user", "content": compress_instruction})

    # Notify frontend that compression is starting
    await context.event_bus.emit(
        AgentEvent(
            type=EventType.COMPRESS_START,
            data={"original_count": len(early) + keep},
        )
    )

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

                if piece:
                    await context.event_bus.emit(
                        AgentEvent(
                            type=EventType.COMPRESS_DELTA,
                            data={"text": piece},
                        )
                    )

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
        logger.warning("Context compression failed after retries, keeping original: %s", last_exc)
        await context.event_bus.emit(
            AgentEvent(
                type=EventType.CONTEXT_COMPRESSED,
                data={
                    "original_count": len(early) + keep,
                    "compressed_count": len(messages),
                    "summary_length": 0,
                    "failed": True,
                },
            )
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
            await persistence.persist_compression(summary)
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

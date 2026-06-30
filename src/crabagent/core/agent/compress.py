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

    history_text = _format_messages(early, max_chars=120_000)
    system_prompt = t("compress.system_prompt", locale)
    user_prompt = t("compress.user_prompt", locale, history=history_text)

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
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=8192,
                stream=True,
                stream_options={"include_usage": True},
            )

            content_buf = ""
            reasoning_buf = ""
            async for chunk in response:
                if not chunk.choices:
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


def _format_messages(messages: list[dict], max_chars: int = 0) -> str:
    """Format messages into a text blob for the compression LLM call.

    When ``max_chars > 0``, the total output is capped at that many
    characters.  Older messages are dropped first (keeping the most
    recent ones), and each message's content is progressively shortened
    so the result always fits within the budget.
    """
    # First pass: collect formatted entries
    entries: list[str] = []
    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")

        # Skip compress ack placeholders — they carry no information
        if msg.get("_compress_ack"):
            continue

        if not content:
            if msg.get("tool_calls"):
                tool_names = [tc.get("function", {}).get("name", "?") for tc in msg["tool_calls"]]
                content = f"[tool calls: {', '.join(tool_names)}]"
            else:
                continue

        if role == "tool":
            tool_name = msg.get("name", "tool")
            entries.append(f"[{tool_name} result]: {content[:2000]}")
        else:
            # Normalise internal roles for display
            display_role = "user" if role in ("agent_switch", "experience", "compress") else role
            display = content[:3000] if len(content) > 3000 else content
            entries.append(f"[{display_role}]: {display}")

    if max_chars <= 0:
        return "\n\n".join(entries)

    # Second pass: enforce character budget
    # Start from the most recent entries and work backwards
    total = 0
    kept: list[str] = []
    per_entry_budget = max_chars
    for entry in reversed(entries):
        if total + len(entry) > max_chars:
            # Truncate this entry to fit remaining budget
            remaining = max_chars - total
            if remaining > 200:
                kept.append(entry[:remaining] + "\n...[truncated]")
            break
        kept.append(entry)
        total += len(entry) + 2  # +2 for "\n\n"
        if total >= max_chars:
            break

    kept.reverse()
    return "\n\n".join(kept)

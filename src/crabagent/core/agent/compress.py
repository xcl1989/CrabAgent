from __future__ import annotations

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

    history_text = _format_messages(early)
    system_prompt = t("compress.system_prompt", locale)
    user_prompt = t("compress.user_prompt", locale, history=history_text)

    # Notify frontend that compression is starting
    await context.event_bus.emit(
        AgentEvent(
            type=EventType.COMPRESS_START,
            data={"original_count": len(early) + keep},
        )
    )

    try:
        response = await litellm.acompletion(
            model=model,
            **llm_params,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1024,
            stream=True,
            stream_options={"include_usage": True},
        )

        summary = ""
        async for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            piece = ""
            if delta.content:
                piece = delta.content
                summary += piece
            elif hasattr(delta, "reasoning_content") and delta.reasoning_content:
                piece = delta.reasoning_content
                summary += piece

            if piece:
                await context.event_bus.emit(
                    AgentEvent(
                        type=EventType.COMPRESS_DELTA,
                        data={"text": piece},
                    )
                )
        summary = summary.strip()
    except Exception as e:
        logger.warning("Context compression failed, keeping original: %s", e)
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


def _format_messages(messages: list[dict]) -> str:
    parts = []
    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if not content:
            if msg.get("tool_calls"):
                tool_names = [tc.get("function", {}).get("name", "?") for tc in msg["tool_calls"]]
                content = f"[tool calls: {', '.join(tool_names)}]"
            else:
                continue

        if role == "tool":
            tool_name = msg.get("name", "tool")
            parts.append(f"[{tool_name} result]: {content[:500]}")
        else:
            # Normalise internal roles for display
            display_role = "user" if role in ("agent_switch", "experience", "compress") else role
            display = content[:1000] if len(content) > 1000 else content
            parts.append(f"[{display_role}]: {display}")

    return "\n\n".join(parts)

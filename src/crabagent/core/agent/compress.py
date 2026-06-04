from __future__ import annotations

import logging

import litellm

from crabagent.core.agent.context import AgentContext
from crabagent.core.config import settings
from crabagent.core.event import AgentEvent, EventType

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = (
    "Summarize the following conversation history concisely. "
    "Preserve key facts, decisions, file paths, and any important context "
    "that would be needed to continue the conversation. "
    "Write in English. Be thorough but concise (aim for 200-500 words).\n\n"
    "Conversation to summarize:\n{history}"
)


async def compress_context(context: AgentContext, llm_params: dict, model: str) -> None:
    keep = settings.context_keep_recent
    messages = context.messages

    if len(messages) <= keep + 2:
        return

    early = messages[:-keep]
    recent = messages[-keep:]

    history_text = _format_messages(early)
    prompt = _SUMMARY_PROMPT.format(history=history_text)

    try:
        response = await litellm.acompletion(
            model=model,
            **llm_params,
            messages=[
                {"role": "system", "content": "You are a conversation summarizer."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1024,
            stream=False,
        )
        summary = ""
        if response.choices:
            msg = response.choices[0].message
            summary = (msg.content or "").strip()
            if not summary:
                reasoning = getattr(msg, "reasoning_content", None)
                if reasoning:
                    summary = reasoning.strip()
    except Exception as e:
        logger.warning("Context compression failed, keeping original: %s", e)
        return

    compressed = [
        {
            "role": "user",
            "content": "[Previous conversation summary]\n" + summary,
        },
        {
            "role": "assistant",
            "content": "Understood. I will continue based on this context summary.",
        },
    ]

    context.messages = compressed + recent
    context.total_tokens = 0
    context.visible_tokens = 0

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
            display = content[:1000] if len(content) > 1000 else content
            parts.append(f"[{role}]: {display}")

    return "\n\n".join(parts)

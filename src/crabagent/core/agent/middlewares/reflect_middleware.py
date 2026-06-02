"""ReflectMiddleware — auto-extract lessons & user preferences after each run.

Fires on ``on_conversation_end``. Rule-based lessons are extracted synchronously
(near-free). Two LLM calls (lesson + user preference extraction) are dispatched
as a background task via ``asyncio.create_task`` so they never block the UI.

1. One technical lesson (:func:`llm_reflect_lesson`)
2. Up to 3 user preferences (:func:`llm_extract_user_preferences`)

Persisted to ``AgentMemory`` with ``source = "llm"``. Skipped when:
- ``settings.memory_auto_extract`` is False
- conversation was < 3 iterations (too short to learn from)
- no user_id in context metadata
- no provider configured
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from crabagent.core.agent.reflect import (
    classify_task,
    llm_extract_user_preferences,
    llm_reflect_lesson,
    persist_lesson,
    persist_preferences,
    rule_extract_lesson,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ReflectMiddleware:
    name = "reflect"

    async def on_conversation_start(self, context) -> None:  # noqa: ARG002
        return None

    async def before_llm_call(self, context, messages: list[dict]) -> list[dict]:  # noqa: ARG002
        return messages

    async def on_conversation_end(self, context) -> None:
        from crabagent.core.config import settings

        if not getattr(settings, "memory_auto_extract", True):
            return

        user_id = context.metadata.get("user_id", 0)
        if not user_id:
            return

        if context.iteration < 3:
            logger.debug("ReflectMiddleware skipped: iteration=%d < 3", context.iteration)
            return

        model = context.metadata.get("_resolved_model") or context.model or ""
        if not model:
            return
        if "/" not in model:
            model = f"openai/{model}"

        provider_name = context.provider_name
        agent_name = context.current_agent or "default"
        session_id = context.metadata.get("session_id", "")
        task = _first_user_message(context.messages)
        if not task:
            return
        task_category = classify_task(task)
        last_assistant_text = _last_assistant_text(context.messages)

        stats = {
            "iterations": context.iteration,
            "max_iterations": context.max_iterations,
            "tokens": context.total_tokens,
            "elapsed": 0.0,
        }
        elapsed_cached = context.metadata.get("_run_elapsed")
        if isinstance(elapsed_cached, (int, float)):
            stats["elapsed"] = float(elapsed_cached)

        # 1. Rule-based lesson (synchronous — no LLM call, near-free)
        rule_lesson = rule_extract_lesson(
            agent_name=agent_name,
            iterations=context.iteration,
            max_iterations=context.max_iterations,
            task=task,
            result=last_assistant_text,
            task_category=task_category,
        )
        if rule_lesson:
            try:
                await persist_lesson(
                    user_id=user_id,
                    agent_name=agent_name,
                    lesson=rule_lesson,
                    source_session=session_id,
                )
            except Exception:
                logger.debug("Failed to persist rule lesson", exc_info=True)

        # 2+3. LLM lesson + user preferences → fire-and-forget in background
        conversation_text = _format_for_preference_extraction(context.messages)
        asyncio.create_task(
            self._reflect_in_background(
                user_id=user_id,
                agent_name=agent_name,
                session_id=session_id,
                task=task,
                last_assistant_text=last_assistant_text,
                task_category=task_category,
                stats=stats,
                model=model,
                provider_name=provider_name,
                conversation_text=conversation_text,
            )
        )

    async def _reflect_in_background(
        self,
        user_id: int,
        agent_name: str,
        session_id: str,
        task: str,
        last_assistant_text: str,
        task_category: str,
        stats: dict,
        model: str,
        provider_name: str | None,
        conversation_text: str,
    ):
        """Background task: LLM lesson + preference extraction run concurrently."""

        async def _extract_lesson():
            try:
                llm_lesson = await llm_reflect_lesson(
                    agent_name=agent_name,
                    task=task,
                    result=last_assistant_text,
                    task_category=task_category,
                    stats=stats,
                    model=model,
                    provider_name=provider_name,
                )
                if llm_lesson:
                    await persist_lesson(
                        user_id=user_id,
                        agent_name=agent_name,
                        lesson=llm_lesson,
                        source_session=session_id,
                    )
            except Exception:
                logger.debug("Background lesson extraction failed", exc_info=True)

        async def _extract_prefs():
            try:
                prefs = await llm_extract_user_preferences(
                    conversation_text=conversation_text,
                    model=model,
                    provider_name=provider_name,
                    max_prefs=3,
                )
                if prefs:
                    saved = await persist_preferences(
                        user_id=user_id,
                        preferences=prefs,
                        source_session=session_id,
                    )
                    if saved:
                        logger.info(
                            "ReflectMiddleware persisted %d user preferences for user=%d",
                            saved,
                            user_id,
                        )
            except Exception:
                logger.debug("Background preference extraction failed", exc_info=True)

        await asyncio.gather(_extract_lesson(), _extract_prefs())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_user_message(messages: list[dict]) -> str:
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text", "")
    return ""


def _last_assistant_text(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return content
    return ""


def _format_for_preference_extraction(messages: list[dict]) -> str:
    """Render the conversation as a compact transcript for preference mining.

    Caps at the last 20 messages and 4000 chars to keep the LLM call cheap.
    Tool calls and tool results are summarised to one-liners.
    """

    lines: list[str] = []
    for msg in messages[-20:]:
        role = msg.get("role", "?")
        content = msg.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            content = " ".join(parts)
        if not isinstance(content, str):
            content = ""
        content = content.strip()
        if not content:
            if msg.get("tool_calls"):
                names = [tc.get("function", {}).get("name", "?") for tc in msg["tool_calls"]]
                content = f"[tool calls: {', '.join(names)}]"
            else:
                continue
        if role == "tool":
            content = f"[tool result] {content[:200]}"
        display = content[:400] if len(content) > 400 else content
        lines.append(f"{role}: {display}")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "...[truncated]"
    return text


__all__ = ["ReflectMiddleware"]

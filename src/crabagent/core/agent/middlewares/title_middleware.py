"""TitleMiddleware — auto-generate conversation title after first exchange.

Fires on ``on_conversation_end``. Fast synchronous checks (DB auto_titled
query) run inline; the actual LLM title call + DB persist is dispatched as a
background task via ``asyncio.create_task`` so it never blocks the UI.

When:
- ``context.metadata["session_id"]`` is set
- the conversation has at least 1 user / 1 assistant message
- the conversation has not been auto-titled yet (``auto_titled`` is False)

…issue one cheap LLM call (~50 tokens) to generate a 4-8 word title and
persist it to the ``conversations`` table.

The middleware is fail-safe: any DB or LLM error is swallowed and logged.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import litellm

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_TITLE_PROMPT = (
    "Generate a concise 4-8 word title for the following conversation exchange. "
    "Use the same language as the user message. "
    "Output ONLY the title text — no quotes, no prefix, no punctuation at the end.\n\n"
    "User: {user}\n\n"
    "Assistant: {assistant}\n\n"
    "Title:"
)


class TitleMiddleware:
    name = "title"

    async def on_conversation_start(self, context) -> None:  # noqa: ARG002
        return None

    async def before_llm_call(self, context, messages: list[dict]) -> list[dict]:  # noqa: ARG002
        return messages

    async def on_conversation_end(self, context) -> None:
        session_id = context.metadata.get("session_id", "")
        if not session_id:
            return

        user_msg = _first_user_text(context.messages)
        assistant_msg = _first_assistant_text(context.messages)
        if not user_msg or not assistant_msg:
            return

        if len(context.messages) > 8:
            return

        model = context.metadata.get("_resolved_model") or context.model or ""
        if not model:
            return
        if "/" not in model:
            model = f"openai/{model}"

        provider_name = context.provider_name

        # Synchronous: check auto_titled status (fast DB query)
        try:
            from sqlalchemy import select

            from crabagent.core.database import Conversation, async_session_factory

            async with async_session_factory() as db:
                row = await db.execute(
                    select(Conversation.title, Conversation.auto_titled).where(Conversation.session_id == session_id)
                )
                existing = row.first()
                if not existing:
                    return
                current_title, auto_titled = existing
                if auto_titled:
                    return
                if current_title and not _is_default_title(current_title):
                    return
        except Exception:
            logger.debug("TitleMiddleware DB check failed", exc_info=True)
            return

        # Fire-and-forget: LLM call + DB update in background
        asyncio.create_task(
            self._title_in_background(
                session_id=session_id,
                user_msg=user_msg,
                assistant_msg=assistant_msg,
                model=model,
                provider_name=provider_name,
            )
        )

    async def _title_in_background(
        self,
        session_id: str,
        user_msg: str,
        assistant_msg: str,
        model: str,
        provider_name: str | None,
    ):
        """Background: generate and persist conversation title."""
        try:
            llm_params = await _resolve_llm_params(provider_name)
            if not llm_params:
                return

            prompt = _TITLE_PROMPT.format(
                user=user_msg[:400],
                assistant=assistant_msg[:400],
            )
            response = await litellm.acompletion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=60,
                temperature=0.2,
                **llm_params,
            )
            title = ""
            if getattr(response, "choices", None):
                msg = response.choices[0].message
                title = (getattr(msg, "content", "") or "").strip()
                if not title:
                    reasoning = getattr(msg, "reasoning_content", None)
                    if reasoning:
                        title = reasoning.strip()
            title = _clean_title(title)
            if not title or len(title) < 2:
                return

            from sqlalchemy import update

            from crabagent.core.database import Conversation, async_session_factory

            async with async_session_factory() as db:
                await db.execute(
                    update(Conversation)
                    .where(Conversation.session_id == session_id)
                    .values(title=title[:200], auto_titled=True)
                )
                await db.commit()
            logger.info("Auto-titled conversation %s: %r", session_id, title)
        except Exception:
            logger.debug("TitleMiddleware background task failed", exc_info=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_user_text(messages: list[dict]) -> str:
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "").strip()
                    if text:
                        return text
    return ""


def _first_assistant_text(messages: list[dict]) -> str:
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


def _is_default_title(title: str) -> bool:
    """A 'default' title is one that the system auto-assigned at creation,
    e.g. 'Conversation 1', 'New Chat', '会话 1'."""
    if not title:
        return True
    t = title.strip().lower()
    defaults = {
        "new conversation",
        "new chat",
        "untitled",
        "conversation",
        "新对话",
        "未命名",
    }
    if t in defaults:
        return True
    # 'conversation N' / '会话 N' patterns
    import re

    if re.match(r"^(conversation|会话|对话|chat)\s*#?\d+$", t):
        return True
    return False


def _clean_title(title: str) -> str:
    import re

    t = title.strip().strip("\"'`")
    # Strip leading "Title:" / "标题:" if the model echoed it
    t = re.sub(r"^(title|标题)\s*[:：]\s*", "", t, flags=re.IGNORECASE)
    # Strip trailing punctuation that's just visual noise
    t = re.sub(r"[.。!!?？]+$", "", t)
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t)
    return t.strip()


async def _resolve_llm_params(provider_name: str | None) -> dict | None:
    try:
        from crabagent.core.provider_store import get_default_provider, get_provider

        provider = await get_provider(provider_name) if provider_name else await get_default_provider()
    except Exception:
        provider = None
    if not provider:
        return None
    params: dict = {"api_key": provider.api_key}
    if provider.base_url:
        params["api_base"] = provider.base_url
        params["custom_llm_provider"] = "openai"
    return params


__all__ = ["TitleMiddleware"]

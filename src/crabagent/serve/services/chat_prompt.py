"""Versioned, memory-free system prompt shared by chat and manual compression."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from crabagent.core.agent.agents import build_team_prompt
from crabagent.core.database import Conversation, async_session_factory
from crabagent.core.i18n import _WEEKDAY_NAMES, get_locale_instruction, get_system_prompt_template, t
from crabagent.core.project_memory import ProjectProfile, get_tech_stack, load_agents_md
from crabagent.serve.services.conversation import update_conversation

logger = logging.getLogger(__name__)
CHAT_PROMPT_SCHEMA_VERSION = 1


async def get_chat_base_prompt(conv: Conversation, workspace: Path, locale: str) -> str:
    if (
        conv.prompt_schema_version == CHAT_PROMPT_SCHEMA_VERSION
        and conv.prompt_locale == locale
        and conv.system_prompt
    ):
        return conv.system_prompt

    now = datetime.now(UTC)
    weekday = _WEEKDAY_NAMES.get(locale, {}).get(now.weekday(), now.strftime("%A"))
    template = get_system_prompt_template(locale) or (
        "You are CrabAgent, an AI assistant. Today is {date} {weekday}. Working directory: {workspace}"
    )
    parts = [template.format(date=now.strftime("%Y-%m-%d"), weekday=weekday, workspace=workspace)]
    try:
        parts.append(await build_team_prompt(locale=locale))
    except Exception:
        logger.warning("Could not build chat team prompt", exc_info=True)

    # ProjectProfile is built from workspace files only, not the memory database.
    parts.append(ProjectProfile(str(workspace), tech_stack=get_tech_stack(workspace)).to_prompt())
    agents_md = load_agents_md(workspace, locale=locale)
    if agents_md:
        parts.append(f'{t("agents_md.section_title", locale)}\n\n{agents_md}')
    parts.append(get_locale_instruction(locale))
    base = "\n\n".join(part for part in parts if part)
    try:
        async with async_session_factory() as db:
            await update_conversation(
                db,
                conv.session_id,
                system_prompt=base,
                prompt_locale=locale,
                prompt_schema_version=CHAT_PROMPT_SCHEMA_VERSION,
            )
    except Exception:
        logger.warning("Could not persist chat base prompt", exc_info=True)
    return base

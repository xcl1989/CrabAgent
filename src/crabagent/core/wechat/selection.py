"""Persist per-sender WeChat selections without trusting display names."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import select

from crabagent.core.database import AppSetting, Conversation, async_session_factory


def key(account: str, sender: str) -> str:
    raw = json.dumps([account, sender], ensure_ascii=True, separators=(",", ":"))
    return "wechat_selection_" + hashlib.sha256(raw.encode()).hexdigest()


async def load(account: str, sender: str) -> dict:
    async with async_session_factory() as db:
        row = await db.scalar(select(AppSetting).where(AppSetting.key == key(account, sender)))
        if row:
            try:
                return json.loads(row.value)
            except (ValueError, TypeError):
                raise ValueError("微信选择记录损坏，请联系管理员处理")
    return {}


async def save(account: str, sender: str, state: dict) -> None:
    async with async_session_factory() as db:
        k = key(account, sender)
        row = await db.scalar(select(AppSetting).where(AppSetting.key == k))
        if not row:
            row = AppSetting(key=k)
            db.add(row)
        row.value = json.dumps(state, ensure_ascii=False)
        await db.commit()


async def conversations(title: str, workspace: str | None = None) -> list[Conversation]:
    async with async_session_factory() as db:
        query = select(Conversation).where(
            Conversation.source == "wechat", Conversation.user_id == 1, Conversation.title == title
        )
        if workspace is not None:
            query = query.where(Conversation.workspace == workspace)
        return list((await db.scalars(query.order_by(Conversation.updated_at.desc(), Conversation.id.desc()))).all())


def workspace_path(value: str) -> str:
    return str(Path(value).expanduser().resolve())


async def available_workspaces(cfg) -> list[str]:
    """Return the configured default and explicitly granted desktop workspaces.

    Desktop history is discovery, not authorization. A grant remains valid only
    while user 1 has a non-WeChat conversation for that workspace.
    """
    default = workspace_path(cfg.workspace or str(Path.cwd()))
    async with async_session_factory() as db:
        result = await db.scalars(
            select(Conversation.workspace).where(
                Conversation.user_id == 1,
                Conversation.source == "chat",
                Conversation.workspace != "",
            )
        )
        registered = set()
        for path in result:
            try:
                registered.add(workspace_path(path))
            except (OSError, RuntimeError, ValueError):
                continue
    available = []
    for path in [default, *cfg.allowed_workspaces]:
        try:
            canonical = workspace_path(path)
            if (canonical == default or canonical in registered) and Path(canonical).is_dir():
                if canonical not in available:
                    available.append(canonical)
        except (OSError, RuntimeError, ValueError):
            continue
    return available

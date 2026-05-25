from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.config import settings
from crabagent.core.database import Molt

logger = logging.getLogger(__name__)


def molt_dir() -> Path:
    return settings.workspace.resolve() / ".crabagent" / "molts"


def snapshot_path(molt_id: str, filepath: str) -> Path:
    return molt_dir() / molt_id / filepath


async def list_molts(db: AsyncSession, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
    result = await db.execute(
        select(Molt)
        .where(Molt.session_id == session_id)
        .order_by(Molt.created_at.desc())
        .limit(limit)
    )
    return [_molt_to_dict(m) for m in result.scalars().all()]


async def get_molt(db: AsyncSession, molt_id: str) -> dict[str, Any] | None:
    result = await db.execute(select(Molt).where(Molt.molt_id == molt_id))
    m = result.scalar_one_or_none()
    return _molt_to_dict(m) if m else None


def _molt_to_dict(m: Molt) -> dict[str, Any]:
    return {
        "molt_id": m.molt_id,
        "session_id": m.session_id,
        "branch_id": m.branch_id,
        "description": m.description,
        "method": m.method,
        "file_count": m.file_count,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


async def create_molt(
    db: AsyncSession,
    molt_id: str,
    session_id: str,
    branch_id: str,
    description: str,
    method: str,
    file_count: int,
) -> dict[str, Any]:
    molt = Molt(
        molt_id=molt_id,
        session_id=session_id,
        branch_id=branch_id,
        description=description,
        method=method,
        file_count=file_count,
    )
    db.add(molt)
    await db.commit()
    await db.refresh(molt)
    return _molt_to_dict(molt)


async def count_molts(db: AsyncSession, session_id: str) -> int:
    result = await db.execute(
        select(Molt).where(Molt.session_id == session_id)
    )
    return len(result.scalars().all())


async def delete_molt(db: AsyncSession, molt_id: str) -> None:
    m = await db.execute(select(Molt).where(Molt.molt_id == molt_id))
    molt = m.scalar_one_or_none()
    if molt:
        await db.delete(molt)
        await db.commit()


async def list_molt_files(molt_id: str) -> list[str]:
    md = molt_dir() / molt_id
    if not md.exists():
        return []
    files = []
    for f in sorted(md.rglob("*")):
        if f.is_file():
            rel = f.relative_to(md)
            files.append(str(rel))
    return files


def get_snapshot_content(molt_id: str, filepath: str) -> str:
    p = snapshot_path(molt_id, filepath)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def get_current_content(workspace: Path, filepath: str) -> str:
    p = workspace / filepath
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


async def prune_molts() -> int:
    from crabagent.core.database import async_session_factory

    keep = settings.molt_keep_count
    pruned = 0
    async with async_session_factory() as db:
        result = await db.execute(
            select(Molt).order_by(Molt.created_at.desc()).offset(keep)
        )
        old_molts = result.scalars().all()
        for m in old_molts:
            md = molt_dir() / m.molt_id
            if md.exists():
                import shutil
                shutil.rmtree(str(md))
            await db.delete(m)
            pruned += 1
        if pruned:
            await db.commit()
            logger.info("Pruned %d old molts", pruned)
    return pruned

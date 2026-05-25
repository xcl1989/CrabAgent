from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import User, get_db
from crabagent.serve.deps import get_current_user, get_owned_conversation

router = APIRouter(prefix="/sessions/{session_id}/molts", tags=["molts"])


@router.get("")
async def list_molts(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await get_owned_conversation(db, session_id, user)
    from crabagent.core.molt.store import list_molts as _list_molts

    return await _list_molts(db, session_id)


@router.get("/{molt_id}")
async def get_molt(
    session_id: str,
    molt_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await get_owned_conversation(db, session_id, user)
    from crabagent.core.molt.store import get_molt as _get_molt
    from crabagent.core.molt.store import list_molt_files

    m = await _get_molt(db, molt_id)
    if not m:
        raise HTTPException(status_code=404, detail="Molt not found")
    m["files"] = await list_molt_files(molt_id)
    return m


@router.get("/{molt_id}/diff")
async def get_molt_diff(
    session_id: str,
    molt_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.config import settings
    from crabagent.core.molt.store import get_current_content, get_snapshot_content, list_molt_files

    files = await list_molt_files(molt_id)
    if not files:
        raise HTTPException(status_code=404, detail="Molt not found")

    diffs = []
    ws = settings.workspace.resolve()
    for fp in files:
        if fp == "diff.txt":
            continue
        old = get_snapshot_content(molt_id, fp)
        new = get_current_content(ws, fp)
        if old != new:
            from difflib import unified_diff
            diff = list(unified_diff(old.splitlines(), new.splitlines(), lineterm=""))
            diffs.append({"file": fp, "diff": "\n".join(diff)})
    return {"molt_id": molt_id, "diffs": diffs}


@router.post("/{molt_id}/rollback")
async def rollback_molt(
    session_id: str,
    molt_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.config import settings
    from crabagent.core.molt.rollback import rollback as _rollback
    from crabagent.core.molt.store import list_molt_files

    files = await list_molt_files(molt_id)
    if not files:
        raise HTTPException(status_code=404, detail="Molt not found")

    workspace = settings.workspace.resolve()
    restored = await _rollback(molt_id, workspace)
    return {"molt_id": molt_id, "restored": len(restored), "files": restored}

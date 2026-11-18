from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.collaboration.auto_binding import normalize_workspace
from crabagent.core.collaboration.claims import intention_text, normalize_scope, overlapping_intentions
from crabagent.core.database import CollaborationBinding, CollaborationEntry, CollaborationProject, User, get_db
from crabagent.serve.deps import get_current_user, get_owned_conversation

router = APIRouter(prefix="/collaboration", tags=["collaboration"])


class ProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    workspace: str = Field(min_length=1)


class VersionItem(BaseModel):
    path: str = Field(min_length=1, max_length=2000)
    version: str = Field(min_length=1, max_length=128)
    absolute: bool = False


class VersionCheckRequest(BaseModel):
    files: list[VersionItem] = Field(min_length=1, max_length=100)


class BindingRequest(BaseModel):
    session_id: str


class EntryRequest(BaseModel):
    session_id: str
    kind: str
    content: str = Field(min_length=1, max_length=10000)
    scope: str = Field(default="", max_length=2000)


async def owned_project(db, project_id, user_id):
    project = await db.get(CollaborationProject, project_id)
    if not project or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def project_data(project):
    return {"id": project.id, "name": project.name, "workspace": project.workspace}


@router.get("/projects")
async def projects(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.execute(select(CollaborationProject).where(CollaborationProject.user_id == user.id))
    return [project_data(row) for row in rows.scalars()]


@router.post("/projects")
async def create_project(
    req: ProjectRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    path = Path(req.workspace).expanduser().resolve()
    if not path.is_dir():
        raise HTTPException(status_code=400, detail="Workspace must be an existing directory")
    existing = await db.execute(
        select(CollaborationProject).where(
            CollaborationProject.user_id == user.id, CollaborationProject.workspace == str(path)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Workspace already belongs to a project")
    project = CollaborationProject(user_id=user.id, name=req.name.strip(), workspace=str(path))
    db.add(project)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Workspace already belongs to a project")
    await db.refresh(project)
    return project_data(project)


@router.post("/projects/{project_id}/check-versions")
async def check_versions(
    project_id: int,
    req: VersionCheckRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Detect modifications by any process; this does not prevent subsequent writes."""
    import asyncio

    from crabagent.core.collaboration.write_coordinator import file_version

    project = await owned_project(db, project_id, user.id)
    workspace = Path(project.workspace).resolve()
    result = []
    for item in req.files:
        raw = Path(item.path)
        if raw.is_absolute() != item.absolute:
            raise HTTPException(status_code=400, detail="Path format does not match absolute flag")
        resolved = raw.resolve() if item.absolute else (workspace / raw).resolve()
        if not resolved.is_relative_to(workspace) or resolved == workspace:
            raise HTTPException(status_code=400, detail="Path outside project workspace")
        if resolved.exists() and not resolved.is_file():
            raise HTTPException(status_code=400, detail="Path must identify a file")
        try:
            current = await asyncio.to_thread(file_version, resolved)
        except OSError:
            raise HTTPException(status_code=403, detail="Cannot read project file")
        result.append({"path": item.path, "version": current, "changed": current != item.version})
    return {"files": result, "guarantee": "observation_only"}


@router.post("/projects/{project_id}/bind")
async def bind_session(
    project_id: int, req: BindingRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    project = await owned_project(db, project_id, user.id)
    conv = await get_owned_conversation(db, req.session_id, user)
    if not conv.workspace or str(Path(conv.workspace).expanduser().resolve()) != project.workspace:
        raise HTTPException(status_code=400, detail="Session workspace does not match project")
    binding = await db.get(CollaborationBinding, req.session_id)
    if binding and binding.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    if binding:
        if binding.project_id != project_id:
            await db.execute(
                update(CollaborationEntry)
                .where(
                    CollaborationEntry.user_id == user.id,
                    CollaborationEntry.project_id == binding.project_id,
                    CollaborationEntry.session_id == req.session_id,
                    CollaborationEntry.kind == "claim",
                    CollaborationEntry.state == "active",
                )
                .values(state="closed")
            )
        binding.project_id = project_id
    else:
        db.add(CollaborationBinding(session_id=req.session_id, user_id=user.id, project_id=project_id))
    conv.collaboration_disabled = False
    await db.commit()
    return {"status": "ok"}


@router.get("/sessions/{session_id}/updates")
async def session_updates(
    session_id: str, after: int = 0, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    conversation = await get_owned_conversation(db, session_id, user)
    binding = await db.get(CollaborationBinding, session_id)
    if conversation.collaboration_disabled or not conversation.workspace or not binding or binding.user_id != user.id:
        return {"project_id": None, "cursor": 0, "entries": []}
    project = await owned_project(db, binding.project_id, user.id)
    if normalize_workspace(conversation.workspace) != project.workspace:
        return {"project_id": None, "cursor": 0, "entries": []}
    rows = await db.execute(
        select(CollaborationEntry)
        .where(
            CollaborationEntry.user_id == user.id,
            CollaborationEntry.project_id == binding.project_id,
            CollaborationEntry.id > max(after, 0),
        )
        .order_by(CollaborationEntry.id.desc() if after <= 0 else CollaborationEntry.id.asc())
        .limit(100)
    )
    scanned = list(rows.scalars())
    return {
        "project_id": binding.project_id,
        "cursor": max([after, *[entry.id for entry in scanned]]),
        "entries": [
            {
                "id": entry.id,
                "session_id": entry.session_id,
                "branch_id": entry.branch_id,
                "kind": entry.kind,
                "scope": entry.scope,
                "content": (
                    (intention_text(entry.content) or "") if entry.kind == "claim" else entry.content.partition("\n")[0]
                )[:400],
            }
            for entry in scanned
            if entry.session_id != session_id or entry.branch_id != (conversation.active_branch or "main")
        ],
    }


@router.get("/sessions/{session_id}/file-activity")
async def file_activity(
    session_id: str,
    path: str,
    include_diff: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.collaboration.events import query_file_activity

    empty = {"intentions": [], "changes": []}
    conversation = await get_owned_conversation(db, session_id, user)
    if conversation.collaboration_disabled or not conversation.workspace:
        return empty
    binding = await db.get(CollaborationBinding, session_id)
    if not binding or binding.user_id != user.id:
        return empty
    project = await owned_project(db, binding.project_id, user.id)
    if normalize_workspace(conversation.workspace) != project.workspace:
        return empty
    try:
        scope = normalize_scope(Path(project.workspace), path, absolute=True)
    except (OSError, RuntimeError, ValueError):
        return empty
    return await query_file_activity(
        db, user.id, project.id, session_id, conversation.active_branch or "main", scope, include_diff=include_diff
    )


@router.get("/projects/{project_id}/entries")
async def entries(
    project_id: int, after: int = 0, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await owned_project(db, project_id, user.id)
    query = select(CollaborationEntry).where(
        CollaborationEntry.user_id == user.id,
        CollaborationEntry.project_id == project_id,
        CollaborationEntry.id > after,
    )
    rows = await db.execute(
        query.order_by(CollaborationEntry.id.asc() if after else CollaborationEntry.id.desc()).limit(200)
    )
    return [
        {
            "id": e.id,
            "session_id": e.session_id,
            "branch_id": e.branch_id,
            "kind": e.kind,
            "content": (intention_text(e.content) or "[expired or legacy write]") if e.kind == "claim" else e.content,
            "scope": e.scope,
            "state": "closed" if e.kind == "claim" and intention_text(e.content) is None else e.state,
            "created_at": e.created_at.isoformat(),
        }
        for e in rows.scalars()
    ]


@router.post("/projects/{project_id}/entries")
async def add_entry(
    project_id: int, req: EntryRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    project = await owned_project(db, project_id, user.id)
    conv = await get_owned_conversation(db, req.session_id, user)
    binding = await db.get(CollaborationBinding, req.session_id)
    if not binding or binding.project_id != project_id or binding.user_id != user.id:
        raise HTTPException(status_code=400, detail="Session is not bound to this project")
    if req.kind not in {"claim", "handoff"}:
        raise HTTPException(status_code=400, detail="Unsupported entry kind")
    branch = conv.active_branch or "main"
    scope = req.scope
    overlaps = []
    if req.kind == "claim":
        try:
            scope = normalize_scope(Path(project.workspace), scope)
        except (ValueError, OSError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        overlaps = await overlapping_intentions(
            db,
            user.id,
            project_id,
            [scope],
            req.session_id,
            branch,
            descendants=True,
        )
    entry = CollaborationEntry(
        user_id=user.id,
        project_id=project_id,
        session_id=req.session_id,
        branch_id=conv.active_branch or "main",
        kind=req.kind,
        content=req.content,
        scope=scope,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return {"id": entry.id, "overlapping_claims": [item["id"] for item in overlaps], "overlapping_intentions": overlaps}


@router.post("/projects/{project_id}/entries/{entry_id}/close")
async def close_entry(
    project_id: int, entry_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await owned_project(db, project_id, user.id)
    entry = await db.get(CollaborationEntry, entry_id)
    if not entry or entry.user_id != user.id or entry.project_id != project_id:
        raise HTTPException(status_code=404, detail="Entry not found")
    entry.state = "closed"
    await db.commit()
    return {"status": "ok"}


@router.post("/projects/{project_id}/unbind")
async def unbind_session(
    project_id: int, req: BindingRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    project = await owned_project(db, project_id, user.id)
    conversation = await get_owned_conversation(db, req.session_id, user)
    binding = await db.get(CollaborationBinding, req.session_id)
    if (binding and (binding.user_id != user.id or binding.project_id != project_id)) or (
        not binding and normalize_workspace(conversation.workspace) != project.workspace
    ):
        raise HTTPException(status_code=404, detail="Binding not found")
    await db.execute(
        update(CollaborationEntry)
        .where(
            CollaborationEntry.user_id == user.id,
            CollaborationEntry.project_id == project_id,
            CollaborationEntry.session_id == req.session_id,
            CollaborationEntry.kind == "claim",
            CollaborationEntry.state == "active",
        )
        .values(state="closed")
    )
    if binding:
        await db.delete(binding)
    conversation.collaboration_disabled = True
    await db.commit()
    return {"status": "ok"}

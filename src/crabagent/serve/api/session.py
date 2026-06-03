from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import Conversation, Message, User, get_db
from crabagent.serve.deps import get_current_user, get_owned_conversation
from crabagent.serve.services import conversation as conv_svc

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    title: str = ""
    workspace: str = ""
    model: str = ""


class UpdateSessionRequest(BaseModel):
    title: str | None = None


class SessionResponse(BaseModel):
    session_id: str
    title: str
    workspace: str
    model: str
    active_branch: str = "main"
    created_at: str | None = None
    updated_at: str | None = None


def _conv_to_response(conv) -> SessionResponse:
    return SessionResponse(
        session_id=conv.session_id,
        title=conv.title,
        workspace=conv.workspace,
        model=conv.model,
        active_branch=conv.active_branch or "main",
        created_at=conv.created_at.isoformat() if conv.created_at else None,
        updated_at=conv.updated_at.isoformat() if conv.updated_at else None,
    )


@router.get("", response_model=list[SessionResponse])
async def list_sessions(
    workspace: str | None = Query(None, description="Filter by workspace path"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    convs = await conv_svc.list_conversations(db, user.id, workspace=workspace)
    return [_conv_to_response(c) for c in convs]


class WorkspaceInfo(BaseModel):
    workspace: str
    session_count: int
    last_active: str | None = None


@router.get("/workspaces", response_model=list[WorkspaceInfo])
async def list_workspaces(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(
            Conversation.workspace,
            Conversation.session_id,
        )
        .where(Conversation.user_id == user.id, Conversation.workspace != "")
        .order_by(Conversation.updated_at.desc())
    )
    rows = result.fetchall()
    seen: dict[str, dict] = {}
    for row in rows:
        ws = row[0]
        if ws not in seen:
            seen[ws] = {"workspace": ws, "session_count": 0, "last_active": None}
        seen[ws]["session_count"] += 1
    return list(seen.values())


@router.get("/current-workspace")
async def get_current_workspace():
    return {"workspace": str(Path.cwd().resolve())}


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    req: CreateSessionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await conv_svc.create_conversation(
        db,
        user_id=user.id,
        workspace=req.workspace,
        model=req.model,
        title=req.title,
    )
    return _conv_to_response(conv)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await get_owned_conversation(db, session_id, user)
    return _conv_to_response(conv)


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str,
    req: UpdateSessionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_conversation(db, session_id, user)
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    conv = await conv_svc.update_conversation(db, session_id, **updates)
    return _conv_to_response(conv)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_conversation(db, session_id, user)
    await conv_svc.delete_conversation(db, session_id)


@router.get("/{session_id}/report", response_class=PlainTextResponse)
async def get_session_report(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await get_owned_conversation(db, session_id, user)
    result = await db.execute(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id))
    msgs = result.scalars().all()

    lines = [f"# {conv.title or 'Conversation Report'}\n"]
    lines.append(f"Session: {session_id}")
    lines.append(f"Created: {conv.created_at.isoformat() if conv.created_at else 'N/A'}\n")

    user_msgs = [m for m in msgs if m.role == "user"]
    assistant_msgs = [m for m in msgs if m.role == "assistant"]
    sub_agent_msgs = [m for m in msgs if m.role == "sub_agent"]

    for m in user_msgs:
        lines.append(f"## User\n\n{m.content or ''}\n")

    for m in sub_agent_msgs:
        try:
            data = json.loads(m.content)
            name = data.get("display_name") or data.get("agent_name") or m.name or "Agent"
            text = data.get("text", m.content)
            elapsed = data.get("elapsed")
            tokens = data.get("tokens")
            iterations = data.get("iterations")
            meta = []
            if elapsed is not None:
                meta.append(f"{elapsed}s")
            if tokens is not None:
                meta.append(f"{tokens} tokens")
            if iterations is not None:
                meta.append(f"{iterations} steps")
            meta_str = f" ({', '.join(meta)})" if meta else ""
            lines.append(f"### {name}{meta_str}\n\n{text}\n")
        except (json.JSONDecodeError, TypeError):
            lines.append(f"### {m.name or 'Agent'}\n\n{m.content or ''}\n")

    for m in assistant_msgs:
        if m.content:
            lines.append(f"## Assistant\n\n{m.content}\n")

    lines.append("---\n")
    lines.append("*Generated by CrabAgent*")
    return "\n".join(lines)


class AgentSwitchRequest(BaseModel):
    agent: str


@router.post("/sessions/{session_id}/agent")
async def switch_agent(
    session_id: str,
    req: AgentSwitchRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = await conv_svc.get_conversation(db, session_id)
    if not conv or conv.user_id != user.id:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Session not found")

    await conv_svc.update_conversation(db, session_id, agent=req.agent)
    return {"status": "ok", "session_id": session_id, "agent": req.agent}

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import Conversation, Message, User, get_db
from crabagent.serve.api.prompt import _tasks
from crabagent.serve.deps import get_current_user, get_owned_conversation
from crabagent.serve.services import conversation as conv_svc
from crabagent.serve.services.message import get_messages, message_to_dict

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    title: str = ""
    workspace: str = ""
    model: str = ""


class UpdateSessionRequest(BaseModel):
    title: str | None = None


class CompressSessionRequest(BaseModel):
    model: str = ""
    provider: str = ""


class CompressSessionResponse(BaseModel):
    summary: str
    model: str
    provider: str
    original_count: int


class SessionResponse(BaseModel):
    session_id: str
    title: str
    workspace: str
    model: str
    provider: str = ""
    agent: str = "default"
    active_branch: str = "main"
    prompt_locale: str = ""
    created_at: str | None = None
    updated_at: str | None = None


def _conv_to_response(conv) -> SessionResponse:
    return SessionResponse(
        session_id=conv.session_id,
        title=conv.title,
        workspace=conv.workspace,
        model=conv.model,
        provider=getattr(conv, "provider", "") or "",
        agent=getattr(conv, "agent", None) or "default",
        active_branch=conv.active_branch or "main",
        prompt_locale=getattr(conv, "prompt_locale", "") or "",
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


class SearchResultItem(BaseModel):
    session_id: str
    title: str
    snippet: str
    role: str
    updated_at: str | None = None


@router.post("/{session_id}/compress", response_model=CompressSessionResponse)
async def compress_session(
    session_id: str,
    req: CompressSessionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Persist a user-triggered compression using the normal compression pipeline."""
    if session_id in _tasks and not _tasks[session_id].done():
        raise HTTPException(status_code=409, detail="Session is already processing a prompt")

    conv = await get_owned_conversation(db, session_id, user)
    branch_id = conv.active_branch or "main"
    records = await get_messages(db, conv.id, branch_id=branch_id)
    records = [msg for msg in records if msg.role not in ("stats",)]
    if len(records) < 2:
        raise HTTPException(status_code=400, detail="Not enough messages to compress")

    from crabagent.core.agent.compress import summarize_messages
    from crabagent.core.agent.loop import _litellm_params, _resolve_provider
    from crabagent.core.config import settings
    from crabagent.core.proxy import resolve_llm_proxy
    from crabagent.serve.services.persistence import PersistenceListener

    provider_name = req.provider or conv.provider or None
    provider = await _resolve_provider(provider_name)
    proxy = await resolve_llm_proxy(provider)
    model_name = req.model or conv.model or settings.default_model
    model = model_name
    if "/" not in model:
        model = f"chatgpt/{model}" if provider.provider_type == "chatgpt" else f"openai/{model}"

    summary = await summarize_messages(
        [message_to_dict(msg) for msg in records],
        system_prompt=conv.system_prompt or "",
        llm_params=_litellm_params(provider, proxy),
        model=model,
        locale=getattr(user, "locale", None) or settings.language or "en",
    )
    if not summary:
        raise HTTPException(status_code=502, detail="Compression model returned an empty summary")

    persistence = PersistenceListener(conversation_id=conv.id, branch_id=branch_id)
    await persistence.persist_compression(summary)

    # The next prompt restores this value into AgentContext before checking the
    # automatic compression threshold. The manual summary replaces that context,
    # so retaining the pre-compression token count would trigger a needless
    # second compression on the next turn.
    conv.tokens = 0
    await db.commit()

    return CompressSessionResponse(
        summary=summary,
        model=model_name,
        provider=provider.name,
        original_count=len(records),
    )


@router.get("/search", response_model=list[SearchResultItem])
async def search_sessions(
    q: str = Query(..., min_length=1, description="Search keyword"),
    workspace: str | None = Query(None, description="Filter by workspace path"),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full-text search across session titles and message content.

    Uses jieba-tokenized FTS5 (messages_fts_cjk) for Chinese + English,
    with LIKE fallback for edge cases.
    """
    seen = set()
    items = []

    # Tokenize query with jieba for CJK-aware FTS5 search
    from crabagent.core.fts import segment as _segment
    tokenized_q = _segment(q).strip() or q
    # Use prefix matching (*) so partial token search works
    # e.g. "项目" → "项目*" matches token "项目管理"
    fts_query = " ".join(t + "*" for t in tokenized_q.split()) if tokenized_q else tokenized_q

    # 1) FTS5-CJK search (jieba-tokenized, handles Chinese + English)
    ws_filter = "AND c.workspace = :workspace" if workspace else ""
    cjk_sql = text(f"""
        SELECT c.session_id, c.title, m.content, m.role, c.updated_at
        FROM messages_fts_cjk
        JOIN messages m ON messages_fts_cjk.rowid = m.id
        JOIN conversations c ON m.conversation_id = c.id
        WHERE messages_fts_cjk MATCH :q
          AND c.user_id = :user_id
          {ws_filter}
          AND m.role IN ('user', 'assistant')
          AND m.compressed = 0
        ORDER BY rank
        LIMIT :lim
    """)
    cjk_params: dict = {"q": fts_query, "user_id": user.id, "lim": limit}
    if workspace:
        cjk_params["workspace"] = workspace
    try:
        result = await db.execute(cjk_sql, cjk_params)
        cjk_rows = result.fetchall()
    except Exception:
        cjk_rows = []

    # 2) LIKE search (catches anything FTS5 misses)
    like_sql = text(f"""
        SELECT c.session_id, c.title, m.content, m.role, c.updated_at
        FROM messages m
        JOIN conversations c ON m.conversation_id = c.id
        WHERE c.user_id = :user_id
          AND m.content LIKE :like_q
          {ws_filter}
          AND m.role IN ('user', 'assistant')
          AND m.compressed = 0
        ORDER BY c.updated_at DESC
        LIMIT :lim
    """)
    like_params: dict = {"like_q": f"%{q}%", "user_id": user.id, "lim": limit}
    if workspace:
        like_params["workspace"] = workspace
    try:
        result = await db.execute(like_sql, like_params)
        like_rows = result.fetchall()
    except Exception:
        like_rows = []

    # 3) Merge: FTS5 first (ranked), then LIKE (deduplicated)
    for row in cjk_rows + like_rows:
        if len(items) >= limit:
            break
        session_id = row[0]
        if session_id in seen:
            continue
        seen.add(session_id)
        content = row[2] or ""
        role = row[3] or "user"
        # Extract plain text from possible JSON content_blocks
        plain = content
        if content.startswith("[") and content.endswith("]"):
            try:
                import json as _j
                blocks = _j.loads(content)
                texts = []
                for b in blocks:
                    if isinstance(b, dict) and b.get("type") == "text":
                        texts.append(b.get("text", ""))
                plain = " ".join(texts)
            except Exception:
                pass
        # Build snippet around match
        idx = plain.lower().find(q.lower())
        if idx >= 0:
            start = max(0, idx - 40)
            end = min(len(plain), idx + len(q) + 40)
            snippet = ("…" if start > 0 else "") + plain[start:end] + ("…" if end < len(plain) else "")
        else:
            snippet = plain[:100]
        items.append(SearchResultItem(
            session_id=session_id,
            title=row[1] or "",
            snippet=snippet,
            role=role,
            updated_at=str(row[4]) if row[4] else None,
        ))

    # Also search titles directly (supplements FTS5 results)
    title_sql = text(f"""
        SELECT session_id, title, updated_at FROM conversations
        WHERE user_id = :user_id
          AND title LIKE :like_q
          {'AND workspace = :workspace' if workspace else ''}
        ORDER BY updated_at DESC
        LIMIT :lim
    """)
    title_params: dict = {"like_q": f"%{q}%", "user_id": user.id, "lim": limit}
    if workspace:
        title_params["workspace"] = workspace
    result = await db.execute(title_sql, title_params)
    for row in result.fetchall():
        if row[0] not in seen:
            items.append(SearchResultItem(
                session_id=row[0],
                title=row[1] or "",
                snippet="",
                role="",
                updated_at=str(row[2]) if row[2] else None,
            ))

    return items[:limit]


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


@router.get("/project-memory")
async def get_project_memory(
    user: User = Depends(get_current_user),
    workspace: str = Query("", description="Workspace path. Defaults to CWD."),
):
    """Return aggregated project memory for the given workspace."""
    ws = Path(workspace).resolve() if workspace else Path.cwd().resolve()
    from crabagent.core.project_memory import load_project_memory

    pm = await load_project_memory(user.id, ws)
    if pm is None:
        return {
            "workspace": str(ws),
            "tech_stack": [],
            "recent_lessons": [],
            "lesson_count": 0,
            "last_active": "",
        }
    return {
        "workspace": pm.workspace,
        "tech_stack": pm.tech_stack,
        "recent_lessons": pm.recent_lessons,
        "lesson_count": pm.lesson_count,
        "last_active": pm.last_active,
    }


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


@router.post("/{session_id}/agent")
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

    # NOTE: agent_switch is NOT persisted here anymore — it's deferred to the next
    # user prompt (prompt.py) to avoid interleaving with in-flight tool_calls/tool
    # responses. The prompt handler compares the last active agent from message
    # history with the current effective_agent and only inserts a switch message
    # when the agent actually changed, placing it before the user's new message.

    return {"status": "ok", "session_id": session_id, "agent": req.agent}


@router.post("/{session_id}/reset-system-prompt")
async def reset_system_prompt(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Clear the cached system prompt so it gets rebuilt with the current locale on next message."""
    conv = await get_owned_conversation(db, session_id, user)
    if conv.system_prompt:
        conv.system_prompt = ""
        conv.prompt_locale = ""
        await db.commit()
    return {"status": "ok", "session_id": session_id}

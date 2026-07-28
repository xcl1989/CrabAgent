"""Safe, user-scoped access to historical conversations."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, text

from crabagent.core.database import Conversation, Message, UserPreference, async_session_factory
from crabagent.core.fts import extract_indexable_text, segment

_SEARCH_ROLES = ("user", "assistant")
_READ_ROLES = ("user", "assistant", "compress")


@dataclass(frozen=True)
class HistorySearchResult:
    session_id: str
    title: str
    workspace: str
    snippet: str
    role: str
    updated_at: str | None


@dataclass(frozen=True)
class HistoryMessage:
    role: str
    content: str


@dataclass(frozen=True)
class HistoryConversation:
    session_id: str
    title: str
    workspace: str
    branch_id: str
    updated_at: str | None
    messages: list[HistoryMessage]
    truncated: bool


def _plain_text(content: str | None) -> str:
    """Return bounded text while dropping multimodal payloads and images."""
    return extract_indexable_text(content or "")


def _snippet(content: str, query: str, limit: int = 240) -> str:
    plain = _plain_text(content)
    if not plain:
        return ""
    position = plain.lower().find(query.lower())
    if position < 0:
        return plain[:limit]
    start = max(0, position - 80)
    end = min(len(plain), position + len(query) + 120)
    value = ("..." if start else "") + plain[start:end] + ("..." if end < len(plain) else "")
    return value[:limit]


async def history_access_enabled(user_id: int) -> bool:
    """Return whether this user explicitly allowed Agent history retrieval."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(UserPreference.value).where(
                UserPreference.user_id == user_id,
                UserPreference.key == "conversation_history_tool_enabled",
            )
        )
        return result.scalar_one_or_none() == "true"


async def search_history(
    *,
    user_id: int,
    query: str,
    workspace: str | None = None,
    exclude_session_id: str | None = None,
    limit: int = 8,
) -> list[HistorySearchResult]:
    """Search only history the requesting user owns and has allowed to be searched."""
    query = query.strip()
    if not query:
        return []
    limit = max(1, min(limit, 20))
    ws_filter = "AND c.workspace = :workspace" if workspace else ""
    current_filter = "AND c.session_id != :exclude_session_id" if exclude_session_id else ""
    tokenized = segment(query).strip() or query
    fts_query = " ".join(f"{token}*" for token in tokenized.split())
    params: dict[str, object] = {"user_id": user_id, "limit": limit, "query": fts_query, "like_query": f"%{query}%"}
    if workspace:
        params["workspace"] = workspace
    if exclude_session_id:
        params["exclude_session_id"] = exclude_session_id

    fts_sql = text(f"""
        SELECT c.session_id, c.title, c.workspace, m.content, m.role, c.updated_at
        FROM messages_fts_cjk
        JOIN messages AS m ON messages_fts_cjk.rowid = m.id
        JOIN conversations AS c ON m.conversation_id = c.id
        WHERE messages_fts_cjk MATCH :query
          AND c.user_id = :user_id
          AND c.history_searchable = 1
          AND m.role IN ('user', 'assistant')
          AND m.compressed = 0
          {ws_filter} {current_filter}
        ORDER BY rank
        LIMIT :limit
    """)
    like_sql = text(f"""
        SELECT c.session_id, c.title, c.workspace, m.content, m.role, c.updated_at
        FROM messages AS m
        JOIN conversations AS c ON m.conversation_id = c.id
        WHERE c.user_id = :user_id
          AND c.history_searchable = 1
          AND m.content LIKE :like_query
          AND m.role IN ('user', 'assistant')
          AND m.compressed = 0
          {ws_filter} {current_filter}
        ORDER BY c.updated_at DESC
        LIMIT :limit
    """)
    title_sql = text(f"""
        SELECT c.session_id, c.title, c.workspace, '' AS content, '' AS role, c.updated_at
        FROM conversations AS c
        WHERE c.user_id = :user_id
          AND c.history_searchable = 1
          AND c.title LIKE :like_query
          {ws_filter} {current_filter}
        ORDER BY c.updated_at DESC
        LIMIT :limit
    """)

    async with async_session_factory() as db:
        try:
            fts_rows = (await db.execute(fts_sql, params)).fetchall()
        except Exception:
            fts_rows = []
        try:
            like_rows = (await db.execute(like_sql, params)).fetchall()
        except Exception:
            like_rows = []
        title_rows = (await db.execute(title_sql, params)).fetchall()

    results: list[HistorySearchResult] = []
    seen: set[str] = set()
    for row in [*fts_rows, *like_rows, *title_rows]:
        if len(results) >= limit or row[0] in seen:
            continue
        seen.add(row[0])
        results.append(
            HistorySearchResult(
                session_id=row[0],
                title=row[1] or "",
                workspace=row[2] or "",
                snippet=_snippet(row[3] or "", query),
                role=row[4] or "",
                updated_at=row[5].isoformat() if hasattr(row[5], "isoformat") else (str(row[5]) if row[5] else None),
            )
        )
    return results


async def read_history(
    *, user_id: int, session_id: str, branch_id: str | None = None, max_messages: int = 16
) -> HistoryConversation | None:
    """Read a bounded branch after enforcing ownership and discoverability."""
    max_messages = max(1, min(max_messages, 40))
    async with async_session_factory() as db:
        conversation = (
            await db.execute(
                select(Conversation).where(
                    Conversation.session_id == session_id,
                    Conversation.user_id == user_id,
                    Conversation.history_searchable == True,  # noqa: E712
                )
            )
        ).scalar_one_or_none()
        if not conversation:
            return None
        chosen_branch = branch_id or conversation.active_branch or "main"
        rows = (
            (
                await db.execute(
                    select(Message)
                    .where(
                        Message.conversation_id == conversation.id,
                        Message.branch_id == chosen_branch,
                        Message.role.in_(_READ_ROLES),
                    )
                    .order_by(Message.sequence.desc(), Message.id.desc())
                    .limit(max_messages + 1)
                )
            )
            .scalars()
            .all()
        )

    truncated = len(rows) > max_messages
    rows = list(reversed(rows[:max_messages]))
    messages = [HistoryMessage(role=row.role, content=_plain_text(row.content)) for row in rows]
    return HistoryConversation(
        session_id=conversation.session_id,
        title=conversation.title or "",
        workspace=conversation.workspace or "",
        branch_id=chosen_branch,
        updated_at=conversation.updated_at.isoformat() if conversation.updated_at else None,
        messages=messages,
        truncated=truncated,
    )

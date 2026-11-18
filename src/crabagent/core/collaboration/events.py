"""Bounded, file-scoped collaboration activity for cooperating editors."""

from __future__ import annotations

import asyncio
import difflib
from pathlib import Path

from sqlalchemy import func, select

from crabagent.core.collaboration.claims import normalize_scope, other_participant, overlapping_intentions
from crabagent.core.collaboration.write_coordinator import file_version
from crabagent.core.database import (
    CollaborationBinding,
    CollaborationEntry,
    CollaborationProject,
    Conversation,
    async_session_factory,
)


def _text_change(before: bytes, after: bytes, rel: str) -> tuple[str, str]:
    if len(before) + len(after) > 512_000:
        return "Text updated", "[change too large for inline diff]"
    try:
        diff = "".join(
            difflib.unified_diff(
                before.decode("utf-8").splitlines(keepends=True),
                after.decode("utf-8").splitlines(keepends=True),
                fromfile="before/" + rel,
                tofile="after/" + rel,
            )
        )
    except UnicodeDecodeError:
        return "File updated", "[text diff unavailable for this encoding]"
    hunks = [line.split(" @@", 1)[0] + " @@" for line in diff.splitlines() if line.startswith("@@ ")]
    summary = "Changed lines: " + "; ".join(hunks[:3]) if hunks else "Text saved"
    return summary, diff[:16000] + ("\n[diff truncated]" if len(diff) > 16000 else "")


def office_summary(tool: str, arguments: dict) -> str:
    def location(item):
        return " ".join(str(item.get(key) or "")[:150] for key in ("path", "parent", "to", "with")).strip()

    if tool == "office_batch_edit":
        commands = arguments.get("commands") or []
        return "; ".join(
            f"{item.get('command', '')} {location(item)}".strip() for item in commands[:5] if isinstance(item, dict)
        ) + ("; ..." if len(commands) > 5 else "")
    if tool == "office_edit":
        props = arguments.get("props") or {}
        return f"{arguments.get('command') or 'edit'} {arguments.get('element_path') or ''} {location(props)}".strip()
    return "Document created"


async def _project(db, user, session, workspace: str | None = None):
    project = CollaborationProject
    query = (
        select(project)
        .join(CollaborationBinding, CollaborationBinding.project_id == project.id)
        .where(
            CollaborationBinding.session_id == session,
            CollaborationBinding.user_id == user,
            project.user_id == user,
        )
    )
    if workspace is not None:
        query = query.where(project.workspace == workspace)
    return await db.scalar(query)


async def _write_event(db, project_id, user, session, branch, scope, version, summary, diff=""):
    label = " ".join(summary.split())[:400]
    db.add(
        CollaborationEntry(
            user_id=user,
            project_id=project_id,
            session_id=session,
            branch_id=branch,
            kind="file_changed",
            scope=scope,
            content=f"{label} (committed version: {version})" + ("\n" + diff if diff else ""),
        )
    )
    await db.commit()


async def record_tool_write(context, tool_name: str, raw_path: str, arguments: dict | None = None) -> None:
    user, session = (context.metadata.get(k) for k in ("user_id", "session_id"))
    if not user or not session or not raw_path:
        return
    workspace = Path(context.workspace).resolve()
    try:
        scope = normalize_scope(workspace, str(Path(raw_path).expanduser()), absolute=True)
    except (OSError, RuntimeError, ValueError):
        return
    path = workspace / scope
    change = context.metadata.get("_pending_change_diffs", {}).pop(str(path), None)
    diff = ""
    if change is not None:
        summary, diff = await asyncio.to_thread(_text_change, *change, scope)
    else:
        summary = office_summary(tool_name, arguments or {}) if tool_name.startswith("office_") else tool_name
    version = context.metadata.get("_file_versions", {}).get(str(path)) or await asyncio.to_thread(file_version, path)
    async with async_session_factory() as db:
        project = await _project(db, user, session, str(workspace))
        if project:
            await _write_event(
                db,
                project.id,
                user,
                session,
                context.metadata.get("branch_id") or "main",
                scope,
                version,
                summary,
                diff,
            )


async def query_file_activity(db, user, project_id, session, branch, scope, *, include_diff=False):
    intentions = await overlapping_intentions(db, user, project_id, [scope], session, branch, limit=3)
    entry = CollaborationEntry
    content = entry.content if include_diff else func.substr(entry.content, 1, 420)
    rows = await db.execute(
        select(entry.id, entry.session_id, entry.branch_id, entry.created_at, content)
        .where(
            entry.user_id == user,
            entry.project_id == project_id,
            entry.kind == "file_changed",
            entry.scope == scope,
            other_participant(session, branch),
        )
        .order_by(entry.id.desc())
        .limit(3)
    )
    changes = []
    for event_id, event_session, event_branch, created, text in rows:
        title, _, diff = text.partition("\n")
        diff = diff[:8000] + ("\n[diff truncated]" if len(diff) > 8000 else "")
        changes.append(
            {
                "id": event_id,
                "session": event_session,
                "branch": event_branch,
                "scope": scope,
                "summary": title.split(" (committed version:", 1)[0][:240],
                "at": created.isoformat() if created else "",
                **({"diff": diff} if include_diff else {}),
            }
        )
    return {"intentions": intentions, "changes": changes}


async def tool_file_activity(context, raw_path: str, *, include_diff=False):
    user, session = (context.metadata.get(k) for k in ("user_id", "session_id"))
    if not user or not session or not raw_path:
        return None
    workspace = Path(context.workspace).resolve()
    try:
        scope = normalize_scope(workspace, str(Path(raw_path).expanduser()), absolute=True)
    except (OSError, RuntimeError, ValueError):
        return None
    async with async_session_factory() as db:
        project = await _project(db, user, session, str(workspace))
        if project:
            return scope, await query_file_activity(
                db,
                user,
                project.id,
                session,
                context.metadata.get("branch_id") or "main",
                scope,
                include_diff=include_diff,
            )
    return None


async def record_ui_write(
    user_id: int,
    session_id: str,
    path: Path,
    operation: str,
    result_version: str,
    *,
    summary: str = "",
    change: tuple[bytes, bytes] | None = None,
) -> None:
    if not session_id:
        return
    async with async_session_factory() as db:
        project = await _project(db, user_id, session_id)
        if not project:
            return
        conversation = await db.scalar(
            select(Conversation).where(
                Conversation.session_id == session_id,
                Conversation.user_id == user_id,
            )
        )
        if not conversation or conversation.collaboration_disabled or not conversation.workspace:
            return
        workspace = Path(project.workspace)
        if Path(conversation.workspace).expanduser().resolve() != workspace:
            return
        try:
            scope = normalize_scope(workspace, str(path), absolute=True)
        except (OSError, RuntimeError, ValueError):
            return
        diff = ""
        if change is not None:
            summary, diff = await asyncio.to_thread(_text_change, *change, scope)
        await _write_event(
            db,
            project.id,
            user_id,
            session_id,
            conversation.active_branch or "main",
            scope,
            result_version,
            summary or operation,
            diff,
        )

from __future__ import annotations

import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import Task


def _task_to_dict(t: Task) -> dict:
    return {
        "id": t.id,
        "user_id": t.user_id,
        "title": t.title,
        "description": t.description,
        "assignee": t.assignee,
        "deadline": t.deadline.isoformat() if t.deadline else None,
        "source": t.source,
        "source_ref": t.source_ref,
        "source_session": t.source_session,
        "project": t.project,
        "status": t.status,
        "priority": t.priority,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


async def add_task(
    db: AsyncSession,
    user_id: int,
    title: str,
    description: str = "",
    assignee: str = "",
    deadline: datetime.datetime | None = None,
    source: str = "manual",
    source_ref: str = "",
    source_session: str = "",
    project: str = "",
    priority: str = "medium",
) -> dict:
    task = Task(
        user_id=user_id,
        title=title,
        description=description,
        assignee=assignee,
        deadline=deadline,
        source=source,
        source_ref=source_ref,
        source_session=source_session,
        project=project,
        priority=priority,
        status="pending",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return _task_to_dict(task)


async def list_tasks(
    db: AsyncSession,
    user_id: int,
    status_filter: str = "all",
    project: str = "",
) -> list[dict]:
    stmt = select(Task).where(Task.user_id == user_id)
    if status_filter == "pending":
        stmt = stmt.where(Task.status.in_(["pending", "in_progress"]))
    elif status_filter == "done":
        stmt = stmt.where(Task.status == "done")
    elif status_filter == "overdue":
        now = datetime.datetime.now()
        stmt = stmt.where(
            Task.status.in_(["pending", "in_progress"]),
            Task.deadline < now,
            Task.deadline.isnot(None),
        )
    if project:
        stmt = stmt.where(Task.project == project)
    stmt = stmt.order_by(Task.created_at.desc())
    result = await db.execute(stmt)
    return [_task_to_dict(t) for t in result.scalars().all()]


async def list_tasks_due_soon(
    db: AsyncSession,
    user_id: int,
    within_hours: int = 24,
) -> list[dict]:
    """List tasks with deadlines within the next N hours."""
    now = datetime.datetime.now()
    deadline_end = now + datetime.timedelta(hours=within_hours)
    stmt = (
        select(Task)
        .where(
            Task.user_id == user_id,
            Task.status.in_(["pending", "in_progress"]),
            Task.deadline.isnot(None),
            Task.deadline >= now,
            Task.deadline <= deadline_end,
        )
        .order_by(Task.deadline.asc())
    )
    result = await db.execute(stmt)
    return [_task_to_dict(t) for t in result.scalars().all()]


async def get_task_summary(
    db: AsyncSession,
    user_id: int,
) -> dict:
    """Get summary counts for tasks."""
    from sqlalchemy import func

    now = datetime.datetime.now()
    total = await db.execute(
        select(func.count(Task.id)).where(Task.user_id == user_id)
    )
    pending = await db.execute(
        select(func.count(Task.id)).where(
            Task.user_id == user_id,
            Task.status.in_(["pending", "in_progress"]),
        )
    )
    overdue = await db.execute(
        select(func.count(Task.id)).where(
            Task.user_id == user_id,
            Task.status.in_(["pending", "in_progress"]),
            Task.deadline.isnot(None),
            Task.deadline < now,
        )
    )
    done_today = await db.execute(
        select(func.count(Task.id)).where(
            Task.user_id == user_id,
            Task.status == "done",
            Task.updated_at >= now - datetime.timedelta(days=1),
        )
    )

    return {
        "total": total.scalar() or 0,
        "pending": pending.scalar() or 0,
        "overdue": overdue.scalar() or 0,
        "done_today": done_today.scalar() or 0,
    }


async def get_task(db: AsyncSession, task_id: int, user_id: int) -> dict | None:
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.user_id == user_id)
    )
    t = result.scalar_one_or_none()
    return _task_to_dict(t) if t else None


async def update_task(
    db: AsyncSession,
    task_id: int,
    user_id: int,
    **kwargs,
) -> dict | None:
    allowed = {"title", "description", "assignee", "deadline", "status",
                "priority", "project", "source", "source_ref"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return await get_task(db, task_id, user_id)
    updates["updated_at"] = datetime.datetime.now()
    stmt = (
        update(Task)
        .where(Task.id == task_id, Task.user_id == user_id)
        .values(**updates)
    )
    result = await db.execute(stmt)
    if result.rowcount == 0:
        return None
    await db.commit()
    return await get_task(db, task_id, user_id)


async def delete_task(db: AsyncSession, task_id: int, user_id: int) -> bool:
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.user_id == user_id)
    )
    t = result.scalar_one_or_none()
    if not t:
        return False
    await db.delete(t)
    await db.commit()
    return True


async def list_projects(db: AsyncSession, user_id: int) -> list[dict]:
    """Get all projects with task counts for a user.

    Returns list of dicts: {name, task_count, pending_count, keywords}.
    Keywords are extracted from task titles (top 5 most common non-trivial words).
    """
    from sqlalchemy import func

    # Get all non-empty projects with counts
    stmt = (
        select(
            Task.project,
            func.count(Task.id).label("task_count"),
            func.count(Task.id).filter(Task.status.in_(["pending", "in_progress"])).label("pending_count"),
        )
        .where(Task.user_id == user_id, Task.project != "", Task.project.isnot(None))
        .group_by(Task.project)
        .order_by(func.count(Task.id).desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    # Get titles per project for keyword extraction
    projects = []
    for row in rows:
        title_stmt = (
            select(Task.title)
            .where(Task.user_id == user_id, Task.project == row.project)
            .limit(20)
        )
        title_result = await db.execute(title_stmt)
        titles = [t for (t,) in title_result.all()]
        keywords = _extract_keywords(titles)

        projects.append({
            "name": row.project,
            "task_count": row.task_count,
            "pending_count": row.pending_count,
            "keywords": keywords,
        })

    return projects


def _extract_keywords(titles: list[str], top_n: int = 5) -> list[str]:
    """Extract top keywords from task titles (simple word frequency)."""
    import re
    from collections import Counter

    # Common stop words to ignore
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "about", "and",
        "or", "but", "not", "no", "if", "so", "up", "out", "it", "its",
        "this", "that", "these", "those", "my", "your", "his", "her",
        "our", "their", "what", "which", "who", "when", "where", "how",
        "all", "each", "every", "both", "few", "more", "most", "other",
        "some", "such", "than", "too", "very", "just", "also", "then",
    }

    words = Counter()
    for title in titles:
        # Split on non-alpha, keep words >= 3 chars
        for w in re.findall(r"[a-zA-Z]{3,}", title.lower()):
            if w not in stop_words:
                words[w] += 1

    return [w for w, _ in words.most_common(top_n)]

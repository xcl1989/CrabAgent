"""Trusted work system: unified attention service.

One query surface for "what needs the user right now":

    pending requests  > failed tasks > due human tasks >
    partial tasks     > active runs  > unread results

Consumers (TaskPanel, desktop pet, notification bell, workspace switcher,
daily digest, WeChat) all read from here instead of interpreting
Task.status on their own. Notification read-state is independent from
request handled / result viewed.
"""

from __future__ import annotations

import datetime
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import AgentRun, Task, TaskRequest
from crabagent.core.task.status import TaskStatus

logger = logging.getLogger(__name__)

# Lower number = higher priority (design doc 11 / 5.5).
PENDING_REQUESTS = 0
FAILED_TASKS = 1
DUE_HUMAN_TASKS = 2
PARTIAL_TASKS = 3
ACTIVE_RUNS = 4
UNREAD_RESULTS = 5

_KIND_LABELS = {
    "pending_requests": "等待你的处理",
    "failed_tasks": "失败任务",
    "due_human_tasks": "临近截止",
    "partial_tasks": "部分完成",
    "active_runs": "正在执行",
    "unread_results": "新成果",
}


_REQUEST_TYPE_LABELS = {
    "input": "输入",
    "choice": "选择",
    "approval": "确认",
    "human_step": "人工操作",
    "review": "复核",
}

_STATUS_BY_KIND = {
    "pending_requests": "waiting",
    "failed_tasks": "failed",
    "due_human_tasks": "due",
    "partial_tasks": "partial",
    "active_runs": "working",
    "unread_results": "completed_unread",
}

_KIND_PRIORITY = {
    "pending_requests": 0,
    "failed_tasks": 1,
    "due_human_tasks": 2,
    "partial_tasks": 3,
    "active_runs": 4,
    "unread_results": 5,
}


def _now() -> datetime.datetime:
    return datetime.datetime.now()


def _task_target(task: dict, view: str = "progress") -> dict:
    return {"type": "task", "task_id": task["id"], "view": view, "title": task["title"]}


async def get_attention_summary(db: AsyncSession, user_id: int) -> dict:
    """Collect all attention items, grouped and sorted by priority."""
    now = _now()

    # ── pending blocking requests ──
    request_rows = (
        await db.execute(
            select(TaskRequest, Task.title)
            .outerjoin(Task, TaskRequest.task_id == Task.id)
            .where(TaskRequest.user_id == user_id, TaskRequest.status == "pending")
            .order_by(TaskRequest.created_at.asc())
        )
    ).all()
    pending_requests = [
        {
            "kind": "pending_requests",
            "priority": PENDING_REQUESTS,
            "message": r.title or f"等待你的{_REQUEST_TYPE_LABELS.get(t.request_type, '处理')}",
            "detail": t.question or t.title,
            "target": {
                "type": "task_request",
                "request_id": t.request_key,
                "task_id": t.task_id,
                "session_id": t.session_id,
                "title": r.title or t.title,
            },
            "updated_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t, r in request_rows
    ]

    # ── failed tasks ──
    failed = (
        (
            await db.execute(
                select(Task)
                .where(Task.user_id == user_id, Task.status == TaskStatus.FAILED.value)
                .order_by(Task.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )

    # ── partial tasks ──
    partial = (
        (
            await db.execute(
                select(Task)
                .where(Task.user_id == user_id, Task.status == TaskStatus.PARTIAL.value)
                .order_by(Task.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )

    # ── human-owned tasks due within 24h (or overdue) ──
    due_cutoff = now + datetime.timedelta(hours=24)
    due_human = (
        (
            await db.execute(
                select(Task)
                .where(
                    Task.user_id == user_id,
                    Task.owner_type == "human",
                    Task.status.in_([TaskStatus.PENDING.value, TaskStatus.IN_PROGRESS.value]),
                    Task.deadline.isnot(None),
                    Task.deadline <= due_cutoff,
                )
                .order_by(Task.deadline.asc())
            )
        )
        .scalars()
        .all()
    )

    # ── active agent runs (running runs + in_progress tasks) ──
    running_runs = (
        (
            await db.execute(
                select(AgentRun)
                .where(AgentRun.user_id == user_id, AgentRun.status == "running")
                .order_by(AgentRun.id.desc())
            )
        )
        .scalars()
        .all()
    )
    running_task_ids = {r.task_id for r in running_runs if r.task_id}
    active_tasks = (
        (
            await db.execute(
                select(Task).where(
                    Task.user_id == user_id,
                    Task.status == TaskStatus.IN_PROGRESS.value,
                    Task.id.not_in(running_task_ids) if running_task_ids else True,
                )
            )
        )
        .scalars()
        .all()
    )

    # ── unread results: done/partial with a completion the user never opened ──
    unread = (
        (
            await db.execute(
                select(Task)
                .where(
                    Task.user_id == user_id,
                    Task.status.in_([TaskStatus.DONE.value, TaskStatus.PARTIAL.value]),
                    Task.completed_at.isnot(None),
                    Task.result_viewed_at.is_(None),
                )
                .order_by(Task.completed_at.desc())
            )
        )
        .scalars()
        .all()
    )

    def _task_item(task: Task, kind: str, priority: int, message: str, view: str = "progress") -> dict:
        return {
            "kind": kind,
            "priority": priority,
            "message": message,
            "detail": task.result_summary or task.warning_summary or "",
            "target": _task_target(
                {"id": task.id, "title": task.title},
                view=view,
            ),
            "updated_at": (task.updated_at or task.created_at).isoformat()
            if (task.updated_at or task.created_at)
            else None,
        }

    items: list[dict] = []
    items.extend(pending_requests)
    items.extend(_task_item(t, "failed_tasks", FAILED_TASKS, f"任务失败：{t.title}", view="error") for t in failed)
    items.extend(_task_item(t, "due_human_tasks", DUE_HUMAN_TASKS, f"临近截止：{t.title}") for t in due_human)
    items.extend(_task_item(t, "partial_tasks", PARTIAL_TASKS, f"部分完成：{t.title}", view="result") for t in partial)
    items.extend(_task_item(t, "active_runs", ACTIVE_RUNS, f"正在处理：{t.title}") for t in active_tasks)
    items.extend(
        {
            "kind": "active_runs",
            "priority": ACTIVE_RUNS,
            "message": r.task_summary or f"{r.agent_name} 执行中",
            "detail": r.phase or "",
            "target": (
                _task_target({"id": r.task_id, "title": r.task_summary or ""})
                if r.task_id
                else {"type": "session", "session_id": r.session_id or ""}
            ),
            "updated_at": datetime.datetime.fromtimestamp(r.started_at or 0).isoformat(),
        }
        for r in running_runs
    )
    items.extend(_task_item(t, "unread_results", UNREAD_RESULTS, f"新成果：{t.title}", view="result") for t in unread)

    items.sort(key=lambda item: (item["priority"], item.get("updated_at") or ""))

    grouped = {kind: [] for kind in _KIND_LABELS}
    for item in items:
        grouped.setdefault(item["kind"], []).append(item)

    top = items[0] if items else None
    return {
        "status": top["kind"] if top else "idle",
        "message": top["message"] if top else "随时可以开始",
        "priority": top["priority"] if top is not None else 99,
        "count": len(items),
        "target": top["target"] if top else None,
        "groups": grouped,
        "updated_at": now.isoformat(),
    }


async def get_attention_by_workspace(db: AsyncSession, user_id: int) -> list[dict]:
    """Highest-priority attention state per workspace (switcher badges).

    waiting > failed > due > partial > working > completed_unread.
    """
    summary = await get_attention_summary(db, user_id)
    workspace_of_task: dict[int, str] = {}
    rows = await db.execute(select(Task.id, Task.workspace).where(Task.user_id == user_id))
    for task_id, workspace in rows.all():
        workspace_of_task[task_id] = workspace or "默认工作区"

    buckets: dict[str, dict] = {}
    for kind, items in summary["groups"].items():
        for item in items:
            target = item.get("target") or {}
            task_id = target.get("task_id")
            workspace = workspace_of_task.get(task_id)
            if not workspace:
                continue
            entry = buckets.setdefault(workspace, {"workspace": workspace, "priority": 99, "kinds": set(), "count": 0})
            entry["priority"] = min(entry["priority"], item["priority"])
            entry["kinds"].add(kind)
            entry["count"] += 1

    return [
        {
            "workspace": entry["workspace"],
            "priority": entry["priority"],
            "status": _STATUS_BY_KIND[min(entry["kinds"], key=lambda k: _KIND_PRIORITY[k])],
            "count": entry["count"],
        }
        for entry in sorted(buckets.values(), key=lambda e: e["priority"])
    ]

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import User, get_db
from crabagent.serve.deps import get_current_user

router = APIRouter(prefix="/email", tags=["email"])


class EmailConfigRequest(BaseModel):
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_pass: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    check_interval: int = 300
    enabled: bool = False


@router.get("/config")
async def get_email_config(
    user: User = Depends(get_current_user),
):
    from crabagent.core.mail.config import get_config, _to_dict

    cfg = await get_config(user.id)
    if not cfg:
        return {}
    return _to_dict(cfg)


@router.post("/config")
async def save_email_config(
    req: EmailConfigRequest,
    user: User = Depends(get_current_user),
):
    from crabagent.core.mail.config import save_config as _save
    from crabagent.serve.scheduler import get_scheduler

    cfg = await _save(user.id, req.model_dump(exclude_unset=True))

    # Dynamically update email polling
    sched = get_scheduler()
    if not sched._scheduler.running:
        await sched.start()
    if cfg.enabled and cfg.imap_host:
        sched.start_email_poll_for_user(user.id, cfg.check_interval)
    else:
        sched.stop_email_poll_for_user(user.id)

    from crabagent.core.mail.config import _to_dict

    return _to_dict(cfg)


@router.post("/test")
async def test_email_connection(
    user: User = Depends(get_current_user),
):
    from crabagent.core.mail.config import test_connection

    result = await test_connection(user.id)
    return {"result": result}


@router.post("/check")
async def check_new_emails(
    limit: int = 5,
    user: User = Depends(get_current_user),
):
    from crabagent.core.mail.handler import check_new_emails as _check

    emails = await _check(user.id, limit)
    return {"emails": emails}


@router.post("/daily-digest")
async def send_daily_digest(
    to: str = "",
    user: User = Depends(get_current_user),
):
    from crabagent.core.mail.handler import get_config as _get_mail_cfg
    from crabagent.core.mail.tools import _fmt_task_list
    from crabagent.core.database import async_session_factory
    from crabagent.core.task.store import (
        list_tasks as _list,
        get_task_summary,
        list_tasks_due_soon,
    )

    cfg = await _get_mail_cfg(user.id)
    recipient = to or (cfg.imap_user if cfg else "")

    async with async_session_factory() as db:
        summary = await get_task_summary(db, user.id)
        overdue = await _list(db, user.id, "overdue")
        pending = await _list(db, user.id, "pending")
        due_soon = await list_tasks_due_soon(db, user.id)
        done = await _list(db, user.id, "done")

    import datetime

    today = datetime.datetime.now().strftime("%Y-%m-%d %A")
    lines = [
        f"Daily Digest — {today}",
        "",
        f"Overview:",
        f"  Total: {summary['total']}",
        f"  Pending: {summary['pending']}",
        f"  Overdue: {summary['overdue']}",
        f"  Completed yesterday: {summary['done_today']}",
    ]
    if overdue:
        lines.append("")
        lines.append(f"Overdue ({len(overdue)}):")
        for t in overdue:
            lines.append(f"  - {t['title']} (due {t['deadline'][:10] if t['deadline'] else '?'})")
    if due_soon:
        lines.append("")
        lines.append(f"Due within 24h ({len(due_soon)}):")
        for t in due_soon:
            lines.append(f"  - {t['title']} (due {t['deadline'][:10] if t['deadline'] else '?'})")

    body = "\n".join(lines)
    return {"digest": body, "sent_to": recipient, "summary": summary}


@router.post("/task-remind")
async def send_task_reminder(
    to: str = "",
    user: User = Depends(get_current_user),
):
    from crabagent.core.mail.handler import get_config as _get_mail_cfg
    from crabagent.core.database import async_session_factory
    from crabagent.core.task.store import list_tasks as _list, list_tasks_due_soon

    cfg = await _get_mail_cfg(user.id)
    recipient = to or (cfg.imap_user if cfg else "")

    async with async_session_factory() as db:
        due_soon = await list_tasks_due_soon(db, user.id)
        overdue = await _list(db, user.id, "overdue")

    return {
        "overdue": len(overdue),
        "due_soon": len(due_soon),
        "items": overdue + due_soon,
        "sent_to": recipient,
    }

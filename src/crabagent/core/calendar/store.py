"""Calendar event CRUD + aggregated queries (events + task deadlines).

All functions are async and take an ``AsyncSession``.  Task-derived
events are generated dynamically (not persisted) so they always reflect
the latest task state.
"""

from __future__ import annotations

import datetime
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import CalendarEvent

logger = logging.getLogger(__name__)


def _event_to_dict(e: CalendarEvent) -> dict:
    return {
        "id": e.id,
        "user_id": e.user_id,
        "title": e.title,
        "description": e.description,
        "start_time": e.start_time.isoformat() if e.start_time else None,
        "end_time": e.end_time.isoformat() if e.end_time else None,
        "all_day": e.all_day,
        "type": e.type,
        "source": e.source,
        "linked_task_id": e.linked_task_id,
        "project": e.project,
        "location": e.location,
        "color": e.color,
        "reminder_minutes": e.reminder_minutes,
        "reminder_sent": e.reminder_sent,
        "ical_uid": e.ical_uid,
        "ical_source_id": e.ical_source_id,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def add_event(
    db: AsyncSession,
    user_id: int,
    title: str,
    start_time: datetime.datetime,
    end_time: datetime.datetime | None = None,
    all_day: bool = False,
    description: str = "",
    location: str = "",
    project: str = "",
    event_type: str = "manual",
    source: str = "manual",
    linked_task_id: int | None = None,
    reminder_minutes: int = 15,
    color: str = "",
    ical_uid: str = "",
    ical_source_id: int | None = None,
) -> dict:
    e = CalendarEvent(
        user_id=user_id,
        title=title,
        description=description,
        start_time=start_time,
        end_time=end_time,
        all_day=all_day,
        type=event_type,
        source=source,
        linked_task_id=linked_task_id,
        project=project,
        location=location,
        color=color,
        reminder_minutes=reminder_minutes,
        ical_uid=ical_uid,
        ical_source_id=ical_source_id,
    )
    db.add(e)
    await db.commit()
    await db.refresh(e)
    return _event_to_dict(e)


async def get_event(db: AsyncSession, event_id: int, user_id: int) -> dict | None:
    result = await db.execute(
        select(CalendarEvent).where(
            CalendarEvent.id == event_id,
            CalendarEvent.user_id == user_id,
        )
    )
    e = result.scalar_one_or_none()
    return _event_to_dict(e) if e else None


async def update_event(
    db: AsyncSession,
    event_id: int,
    user_id: int,
    **kwargs,
) -> dict | None:
    allowed = {
        "title", "description", "start_time", "end_time", "all_day",
        "type", "source", "linked_task_id", "project", "location",
        "color", "reminder_minutes", "reminder_sent",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return await get_event(db, event_id, user_id)
    updates["updated_at"] = datetime.datetime.now()
    from sqlalchemy import update as sa_update

    stmt = (
        sa_update(CalendarEvent)
        .where(CalendarEvent.id == event_id, CalendarEvent.user_id == user_id)
        .values(**updates)
    )
    result = await db.execute(stmt)
    if result.rowcount == 0:
        return None
    await db.commit()
    return await get_event(db, event_id, user_id)


async def delete_event(db: AsyncSession, event_id: int, user_id: int) -> bool:
    result = await db.execute(
        select(CalendarEvent).where(
            CalendarEvent.id == event_id,
            CalendarEvent.user_id == user_id,
        )
    )
    e = result.scalar_one_or_none()
    if not e:
        return False
    await db.delete(e)
    await db.commit()
    return True


async def find_by_ical_uid(
    db: AsyncSession, ical_uid: str, ical_source_id: int, user_id: int
) -> dict | None:
    """Find an event by its iCal UID (for upsert during sync)."""
    if not ical_uid:
        return None
    result = await db.execute(
        select(CalendarEvent).where(
            CalendarEvent.ical_uid == ical_uid,
            CalendarEvent.ical_source_id == ical_source_id,
            CalendarEvent.user_id == user_id,
        )
    )
    e = result.scalar_one_or_none()
    return _event_to_dict(e) if e else None


# ---------------------------------------------------------------------------
# Aggregated queries
# ---------------------------------------------------------------------------

async def list_events(
    db: AsyncSession,
    user_id: int,
    start: datetime.datetime,
    end: datetime.datetime,
) -> list[dict]:
    """Return events in [start, end), merged with task-deadline pseudo-events."""
    # 1. Persisted events
    stmt = (
        select(CalendarEvent)
        .where(
            CalendarEvent.user_id == user_id,
            CalendarEvent.start_time >= start,
            CalendarEvent.start_time < end,
        )
        .order_by(CalendarEvent.start_time)
    )
    result = await db.execute(stmt)
    events = [_event_to_dict(e) for e in result.scalars().all()]

    # 2. Task-deadline pseudo-events (dynamic, not persisted)
    try:
        from crabagent.core.database import Task

        task_stmt = (
            select(Task)
            .where(
                Task.user_id == user_id,
                Task.deadline.isnot(None),
                Task.deadline >= start,
                Task.deadline < end,
                Task.status.in_(["pending", "in_progress"]),
            )
            .order_by(Task.deadline)
        )
        task_result = await db.execute(task_stmt)
        for t in task_result.scalars().all():
            # all_day = True only when deadline is at midnight (date-only)
            is_date_only = (
                t.deadline and
                t.deadline.hour == 0 and
                t.deadline.minute == 0 and
                t.deadline.second == 0
            )
            events.append({
                "id": f"task_{t.id}",
                "title": f"⏰ {t.title}",
                "description": t.description or "",
                "start_time": t.deadline.isoformat(),
                "end_time": t.deadline.replace(hour=23, minute=59).isoformat() if is_date_only else None,
                "all_day": is_date_only,
                "type": "task",
                "source": "task",
                "linked_task_id": t.id,
                "project": t.project,
                "location": "",
                "color": "",
                "priority": t.priority,
                "status": t.status,
            })
    except Exception as e:
        logger.debug("Task deadline merge skipped: %s", e)

    # 3. Sort by start_time
    events.sort(key=lambda e: e.get("start_time", ""))
    return events


async def get_today_overview(db: AsyncSession, user_id: int) -> dict:
    """Return today's events, due tasks, and free time slots."""
    now = datetime.datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + datetime.timedelta(days=1)

    events = await list_events(db, user_id, today_start, tomorrow_start)

    # Separate timed events (for free-slot calculation) from all-day
    timed_events = [e for e in events if not e.get("all_day") and e.get("end_time")]
    all_day_events = [e for e in events if e.get("all_day")]

    # Calculate free slots (9:00–18:00 work hours)
    busy = []
    for e in timed_events:
        start_str = e["start_time"]
        end_str = e["end_time"]
        try:
            s = datetime.datetime.fromisoformat(start_str)
            en = datetime.datetime.fromisoformat(end_str)
            busy.append((s, en))
        except Exception:
            pass

    free_slots = _calculate_free_time(busy, today_start.replace(hour=9), today_start.replace(hour=18))

    # Tasks due today (any type=="task" event)
    due_tasks = [e for e in events if e.get("type") == "task"]

    return {
        "date": today_start.date().isoformat(),
        "events": events,
        "timed_events": len(timed_events),
        "all_day_events": len(all_day_events),
        "due_tasks": due_tasks,
        "free_slots": free_slots,
        "summary": (
            f"今天 {len(timed_events)} 个日程、{len(due_tasks)} 个任务到期、"
            f"{len(free_slots)} 段空闲时间"
        ),
    }


def _calculate_free_time(
    busy: list[tuple[datetime.datetime, datetime.datetime]],
    day_start: datetime.datetime,
    day_end: datetime.datetime,
) -> list[dict]:
    """Calculate free time slots given busy intervals within work hours."""
    if not busy:
        return [{"start": day_start.isoformat(), "end": day_end.isoformat()}]

    # Sort by start time
    busy.sort(key=lambda x: x[0])

    slots: list[dict] = []
    cursor = day_start

    for b_start, b_end in busy:
        # Clamp to work hours
        b_start = max(b_start, day_start)
        b_end = min(b_end, day_end)
        if b_start > cursor:
            slots.append({
                "start": cursor.isoformat(),
                "end": b_start.isoformat(),
                "duration_min": int((b_start - cursor).total_seconds() / 60),
            })
        cursor = max(cursor, b_end)

    if cursor < day_end:
        slots.append({
            "start": cursor.isoformat(),
            "end": day_end.isoformat(),
            "duration_min": int((day_end - cursor).total_seconds() / 60),
        })

    return slots


# ---------------------------------------------------------------------------
# Calendar settings (stored in app_settings as JSON)
# ---------------------------------------------------------------------------

_DEFAULT_SETTINGS = {
    "morning_brief_enabled": False,
    "morning_brief_time": "08:00",
    "morning_brief_channel": "wechat",
    "event_reminder_enabled": True,
    "default_reminder_minutes": 15,  # used for iCal-synced events
}


async def load_calendar_settings(db: AsyncSession) -> dict:
    """Load calendar settings from app_settings."""
    import json

    from crabagent.core.database import AppSetting

    result = await db.execute(
        select(AppSetting).where(AppSetting.key == "calendar_settings")
    )
    row = result.scalar_one_or_none()
    if row and row.value:
        try:
            saved = json.loads(row.value)
            return {**_DEFAULT_SETTINGS, **saved}
        except json.JSONDecodeError:
            pass
    return dict(_DEFAULT_SETTINGS)


async def save_calendar_settings(db: AsyncSession, settings: dict) -> dict:
    """Save calendar settings to app_settings."""
    import json

    from crabagent.core.database import AppSetting

    merged = {**_DEFAULT_SETTINGS, **settings}
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == "calendar_settings")
    )
    row = result.scalar_one_or_none()
    if row:
        row.value = json.dumps(merged, ensure_ascii=False)
    else:
        db.add(AppSetting(key="calendar_settings", value=json.dumps(merged, ensure_ascii=False)))
    await db.commit()
    return merged

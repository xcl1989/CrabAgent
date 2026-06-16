"""Calendar REST API — events CRUD, today overview, iCal sources, settings."""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import User, get_db
from crabagent.serve.deps import get_current_user

router = APIRouter(prefix="/calendar", tags=["calendar"])


# ---------------------------------------------------------------------------
# Event schemas
# ---------------------------------------------------------------------------

class CreateEventRequest(BaseModel):
    title: str
    start_time: str  # ISO format
    end_time: str | None = None
    all_day: bool = False
    description: str = ""
    location: str = ""
    project: str = ""
    reminder_minutes: int = 15


class UpdateEventRequest(BaseModel):
    title: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    all_day: bool | None = None
    description: str | None = None
    location: str | None = None
    project: str | None = None
    reminder_minutes: int | None = None


# ---------------------------------------------------------------------------
# Event CRUD
# ---------------------------------------------------------------------------

@router.get("/events")
async def list_events(
    start: str = "",
    end: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.calendar.store import list_events as _list

    now = datetime.datetime.now()
    start_dt = (
        datetime.datetime.fromisoformat(start)
        if start
        else now.replace(hour=0, minute=0, second=0, microsecond=0)
    )
    end_dt = (
        datetime.datetime.fromisoformat(end)
        if end
        else start_dt + datetime.timedelta(days=7)
    )
    # Day view passes same start/end date — ensure end is exclusive
    if end_dt <= start_dt:
        end_dt = start_dt + datetime.timedelta(days=1)
    return await _list(db, user.id, start_dt, end_dt)


@router.post("/events")
async def create_event(
    req: CreateEventRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.calendar.store import add_event

    start_dt = datetime.datetime.fromisoformat(req.start_time)
    end_dt = datetime.datetime.fromisoformat(req.end_time) if req.end_time else None

    return await add_event(
        db,
        user_id=user.id,
        title=req.title,
        start_time=start_dt,
        end_time=end_dt,
        all_day=req.all_day,
        description=req.description,
        location=req.location,
        project=req.project,
        event_type="manual",
        source="manual",
        reminder_minutes=req.reminder_minutes,
    )


@router.put("/events/{event_id}")
async def update_event(
    event_id: int,
    req: UpdateEventRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.calendar.store import update_event as _update

    kwargs = req.model_dump(exclude_none=True)
    if "start_time" in kwargs:
        kwargs["start_time"] = datetime.datetime.fromisoformat(kwargs["start_time"])
    if "end_time" in kwargs:
        kwargs["end_time"] = datetime.datetime.fromisoformat(kwargs["end_time"])

    result = await _update(db, event_id, user.id, **kwargs)
    if not result:
        raise HTTPException(404, "Event not found")
    return result


@router.delete("/events/{event_id}")
async def delete_event(
    event_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.calendar.store import delete_event as _delete

    ok = await _delete(db, event_id, user.id)
    if not ok:
        raise HTTPException(404, "Event not found")
    return {"ok": True}


@router.get("/today")
async def today_overview(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.calendar.store import get_today_overview

    return await get_today_overview(db, user.id)


# ---------------------------------------------------------------------------
# iCal sources
# ---------------------------------------------------------------------------

class CreateIcalSourceRequest(BaseModel):
    name: str
    url: str
    source_type: str = "ical"  # "ical" | "caldav"
    caldav_username: str = ""
    caldav_password: str = ""
    lookback_days: int = 7
    lookahead_days: int = 30


@router.get("/ical-sources")
async def list_ical_sources(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select

    from crabagent.core.database import CalendarIcalSource

    result = await db.execute(
        select(CalendarIcalSource).where(CalendarIcalSource.user_id == user.id)
    )
    sources = result.scalars().all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "url": s.url[:60] + "..." if len(s.url) > 60 else s.url,
            "source_type": getattr(s, "source_type", "ical") or "ical",
            "enabled": s.enabled,
            "last_sync_at": s.last_sync_at.isoformat() if s.last_sync_at else None,
            "last_sync_status": s.last_sync_status,
            "sync_event_count": s.sync_event_count,
            "last_error": s.last_error[:200] if s.last_error else "",
        }
        for s in sources
    ]


@router.post("/ical-sources")
async def create_ical_source(
    req: CreateIcalSourceRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.database import CalendarIcalSource

    source = CalendarIcalSource(
        user_id=user.id,
        name=req.name,
        url=req.url,
        source_type=req.source_type,
        caldav_username=req.caldav_username,
        caldav_password=req.caldav_password,
        lookback_days=req.lookback_days,
        lookahead_days=req.lookahead_days,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return {"id": source.id, "name": source.name, "enabled": source.enabled}


@router.delete("/ical-sources/{source_id}")
async def delete_ical_source(
    source_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import delete as sa_delete, select

    from crabagent.core.database import CalendarEvent, CalendarIcalSource

    result = await db.execute(
        select(CalendarIcalSource).where(
            CalendarIcalSource.id == source_id,
            CalendarIcalSource.user_id == user.id,
        )
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(404, "Source not found")

    # Delete synced events
    await db.execute(
        sa_delete(CalendarEvent).where(
            CalendarEvent.ical_source_id == source_id,
            CalendarEvent.user_id == user.id,
        )
    )
    await db.delete(source)
    await db.commit()
    return {"ok": True}


@router.post("/ical-sources/{source_id}/sync")
async def sync_ical_source(
    source_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select

    from crabagent.core.calendar.ical_sync import sync_source
    from crabagent.core.database import CalendarIcalSource

    result = await db.execute(
        select(CalendarIcalSource).where(
            CalendarIcalSource.id == source_id,
            CalendarIcalSource.user_id == user.id,
        )
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(404, "Source not found")

    try:
        count = await sync_source(db, source)
        return {"ok": True, "synced": count}
    except Exception as e:
        raise HTTPException(500, str(e))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class CalendarSettingsRequest(BaseModel):
    morning_brief_enabled: bool | None = None
    morning_brief_time: str | None = None
    morning_brief_channel: str | None = None
    event_reminder_enabled: bool | None = None


@router.get("/settings")
async def get_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.calendar.store import load_calendar_settings

    return await load_calendar_settings(db)


@router.put("/settings")
async def update_settings(
    req: CalendarSettingsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.calendar.store import save_calendar_settings

    kwargs = req.model_dump(exclude_none=True)
    result = await save_calendar_settings(db, kwargs)

    # If morning brief time changed, reschedule the job
    if "morning_brief_time" in kwargs:
        try:
            from crabagent.serve.scheduler import get_scheduler

            get_scheduler().reschedule_morning_brief(kwargs["morning_brief_time"])
        except Exception:
            pass

    return result

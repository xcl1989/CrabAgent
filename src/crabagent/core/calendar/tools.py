"""Agent tools for the built-in calendar system.

Registers 5 tools: calendar_add, calendar_list, calendar_today,
calendar_update, calendar_delete.
"""

from __future__ import annotations

import datetime
import logging

logger = logging.getLogger(__name__)


def register_calendar_tools(registry):
    """Register all calendar tools with the given registry."""

    @registry.register(
        name="calendar_add",
        description=(
            "Add a calendar event. Use when the user mentions a meeting, "
            "appointment, or scheduled activity. "
            "Examples: '明天下午3点开会', '下周二有个培训'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title"},
                "start_time": {
                    "type": "string",
                    "description": "Start time: 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DD'",
                },
                "end_time": {
                    "type": "string",
                    "description": "End time (optional). Same format as start_time.",
                },
                "all_day": {
                    "type": "boolean",
                    "description": "Whether this is an all-day event",
                },
                "description": {"type": "string", "description": "Optional description"},
                "location": {"type": "string", "description": "Optional location"},
                "project": {"type": "string", "description": "Associated project"},
                "reminder_minutes": {
                    "type": "integer",
                    "description": "Reminder N minutes before (default 15, 0=no reminder)",
                },
            },
            "required": ["title", "start_time"],
        },
    )
    async def calendar_add(
        title: str,
        start_time: str,
        end_time: str = "",
        all_day: bool = False,
        description: str = "",
        location: str = "",
        project: str = "",
        reminder_minutes: int = 15,
        context=None,
    ) -> str:
        from crabagent.core.calendar.store import add_event
        from crabagent.core.database import async_session_factory

        start_dt = _parse_datetime(start_time)
        if not start_dt:
            return f"❌ 无法解析时间: {start_time}"

        end_dt = _parse_datetime(end_time) if end_time else None

        # If no time component was given, treat as all-day
        if " " not in start_time and not end_time:
            all_day = True

        user_id = _get_user_id(context)
        async with async_session_factory() as db:
            e = await add_event(
                db,
                user_id=user_id,
                title=title,
                start_time=start_dt,
                end_time=end_dt,
                all_day=all_day,
                description=description,
                location=location,
                project=project,
                event_type="agent",
                source="agent",
                reminder_minutes=reminder_minutes,
            )
        parts = [f"📅 事件已创建: **{title}**"]
        parts.append(f"⏰ {start_dt.strftime('%m-%d %H:%M') if not all_day else start_dt.strftime('%m-%d')}")
        if location:
            parts.append(f"📍 {location}")
        if reminder_minutes > 0:
            parts.append(f"🔔 提前{reminder_minutes}分钟提醒")
        return " | ".join(parts)

    @registry.register(
        name="calendar_list",
        description=(
            "List calendar events in a date range (includes task deadlines). "
            "Use when the user asks '这周有什么安排', '明天有什么会议', etc."
        ),
        parameters={
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date 'YYYY-MM-DD' (default: today)",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date 'YYYY-MM-DD' (default: today + 7 days)",
                },
            },
        },
    )
    async def calendar_list(
        start_date: str = "",
        end_date: str = "",
        context=None,
    ) -> str:
        from crabagent.core.calendar.store import list_events
        from crabagent.core.database import async_session_factory

        now = datetime.datetime.now()
        start_dt = _parse_date(start_date) or now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = _parse_date(end_date) or (start_dt + datetime.timedelta(days=7))

        user_id = _get_user_id(context)
        async with async_session_factory() as db:
            events = await list_events(db, user_id, start_dt, end_dt + datetime.timedelta(days=1))

        if not events:
            return f"📅 {start_dt.strftime('%m-%d')} 到 {end_dt.strftime('%m-%d')} 没有事件。"

        lines = [f"📅 {start_dt.strftime('%m-%d')} ~ {end_dt.strftime('%m-%d')} 事件列表:"]
        current_day = ""
        for e in events:
            day = e["start_time"][:10] if e["start_time"] else "?"
            if day != current_day:
                current_day = day
                lines.append(f"\n  📌 {day}")
            time_part = ""
            if not e.get("all_day") and e["start_time"]:
                try:
                    dt = datetime.datetime.fromisoformat(e["start_time"])
                    time_part = f"{dt.strftime('%H:%M')} "
                except Exception:
                    pass

            type_icon = {"task": "⏰", "manual": "🟡", "agent": "🟢", "external": "🔵"}.get(e.get("type"), "📅")
            lines.append(f"    {time_part}{type_icon} {e['title']}")
            if e.get("location"):
                lines.append(f"       📍 {e['location']}")

        return "\n".join(lines)

    @registry.register(
        name="calendar_today",
        description=(
            "Get today's overview: events, due tasks, and free time slots. "
            "Use when the user asks '今天有什么安排'."
        ),
        parameters={"type": "object", "properties": {}},
    )
    async def calendar_today(context=None) -> str:
        from crabagent.core.calendar.store import get_today_overview
        from crabagent.core.database import async_session_factory

        user_id = _get_user_id(context)
        async with async_session_factory() as db:
            overview = await get_today_overview(db, user_id)

        lines = [f"📅 {overview['date']} 今日概览\n"]
        lines.append(f"📊 {overview['summary']}\n")

        # Events
        timed = [e for e in overview["events"] if not e.get("all_day")]
        all_day = [e for e in overview["events"] if e.get("all_day")]

        if timed:
            lines.append("🕐 日程:")
            for e in timed:
                time_str = ""
                if e["start_time"]:
                    try:
                        dt = datetime.datetime.fromisoformat(e["start_time"])
                        time_str = f"{dt.strftime('%H:%M')}"
                        if e.get("end_time"):
                            dt2 = datetime.datetime.fromisoformat(e["end_time"])
                            time_str += f"-{dt2.strftime('%H:%M')}"
                    except Exception:
                        pass
                icon = {"manual": "🟡", "agent": "🟢", "external": "🔵"}.get(e.get("type"), "📅")
                loc = f" 📍{e['location']}" if e.get("location") else ""
                lines.append(f"  {time_str} {icon} {e['title']}{loc}")
            lines.append("")

        if all_day:
            lines.append("📌 全天/截止:")
            for e in all_day:
                lines.append(f"  {e['title']}")
            lines.append("")

        # Free slots
        if overview["free_slots"]:
            lines.append("🟢 空闲时段:")
            for slot in overview["free_slots"]:
                try:
                    s = datetime.datetime.fromisoformat(slot["start"])
                    en = datetime.datetime.fromisoformat(slot["end"])
                    dur = slot.get("duration_min", 0)
                    hours = dur // 60
                    mins = dur % 60
                    dur_str = f"{hours}h{mins}m" if hours else f"{mins}m"
                    lines.append(f"  {s.strftime('%H:%M')}-{en.strftime('%H:%M')} ({dur_str})")
                except Exception:
                    pass

        return "\n".join(lines)

    @registry.register(
        name="calendar_update",
        description=(
            "Update a calendar event. Use to change title, time, "
            "location, or reminder."
        ),
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Event ID"},
                "title": {"type": "string", "description": "New title"},
                "start_time": {"type": "string", "description": "New start time"},
                "end_time": {"type": "string", "description": "New end time"},
                "location": {"type": "string", "description": "New location"},
                "reminder_minutes": {
                    "type": "integer",
                    "description": "Reminder minutes (0=no reminder)",
                },
            },
            "required": ["id"],
        },
    )
    async def calendar_update(
        id: int,
        title: str = "",
        start_time: str = "",
        end_time: str = "",
        location: str = "",
        reminder_minutes: int = -1,
        context=None,
    ) -> str:
        from crabagent.core.calendar.store import update_event
        from crabagent.core.database import async_session_factory

        kwargs = {}
        if title:
            kwargs["title"] = title
        if start_time:
            dt = _parse_datetime(start_time)
            if dt:
                kwargs["start_time"] = dt
        if end_time:
            dt = _parse_datetime(end_time)
            if dt:
                kwargs["end_time"] = dt
        if location:
            kwargs["location"] = location
        if reminder_minutes >= 0:
            kwargs["reminder_minutes"] = reminder_minutes

        if not kwargs:
            return "⚠️ 没有需要更新的字段。"

        user_id = _get_user_id(context)
        async with async_session_factory() as db:
            e = await update_event(db, id, user_id, **kwargs)
        if e:
            return f"✅ 事件已更新: **{e['title']}**"
        return f"❌ 事件 {id} 不存在。"

    @registry.register(
        name="calendar_delete",
        description="Delete a calendar event.",
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Event ID"},
            },
            "required": ["id"],
        },
    )
    async def calendar_delete(id: int, context=None) -> str:
        from crabagent.core.calendar.store import delete_event
        from crabagent.core.database import async_session_factory

        user_id = _get_user_id(context)
        async with async_session_factory() as db:
            ok = await delete_event(db, id, user_id)
        return f"🗑️ 事件 {id} 已删除。" if ok else f"❌ 事件 {id} 不存在。"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_id(context) -> int:
    if context:
        return int(context.metadata.get("user_id", context.metadata.get("uid", 1)))
    return 1


def _parse_datetime(s: str) -> datetime.datetime | None:
    """Parse 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DD' to datetime."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s.strip()[:19], fmt)
        except ValueError:
            continue
    return None


def _parse_date(s: str) -> datetime.datetime | None:
    """Parse 'YYYY-MM-DD' to datetime at start of day."""
    if not s:
        return None
    try:
        return datetime.datetime.strptime(s.strip()[:10], "%Y-%m-%d")
    except ValueError:
        return None

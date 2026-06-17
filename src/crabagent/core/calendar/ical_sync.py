"""External calendar sync — supports ICS URLs and CalDAV protocol.

ICS:   Static URL → httpx.get → icalendar.from_ical → VEVENT[]
CalDAV: PROPFIND → REPORT → list .ics → GET each → VEVENT[]

Both paths feed into the shared ``_upsert_events()`` function.

Requires:
    - ``icalendar`` package (pip install icalendar)
"""

from __future__ import annotations

import asyncio
import datetime
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import CalendarEvent, CalendarIcalSource

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def sync_all_sources(db: AsyncSession, user_id: int = 1) -> dict:
    """Sync all enabled calendar sources for a user.

    Returns ``{"synced": N, "errors": [...]}``.
    """
    result = await db.execute(
        select(CalendarIcalSource).where(
            CalendarIcalSource.user_id == user_id,
            CalendarIcalSource.enabled.is_(True),
        )
    )
    sources = list(result.scalars().all())

    total_synced = 0
    errors = []

    for source in sources:
        try:
            count = await sync_source(db, source)
            total_synced += count
        except Exception as e:
            msg = f"{source.name}: {e}"
            errors.append(msg)
            source.last_sync_status = "error"
            source.last_error = str(e)[:500]
            logger.error("[Calendar] Sync failed for %s: %s", source.name, e)

    await db.commit()
    return {"synced": total_synced, "errors": errors}


async def sync_source(db: AsyncSession, source: CalendarIcalSource) -> int:
    """Sync a single source, dispatching by ``source_type``."""
    stype = getattr(source, "source_type", "ical") or "ical"

    # Load default reminder minutes from calendar settings
    try:
        from crabagent.core.calendar.store import load_calendar_settings
        cfg = await load_calendar_settings(db)
        default_reminder_minutes = cfg.get("default_reminder_minutes", 15)
    except Exception:
        default_reminder_minutes = 15

    if stype == "caldav":
        return await _sync_caldav_source(db, source, default_reminder_minutes)
    return await _sync_ical_source(db, source, default_reminder_minutes)


# ---------------------------------------------------------------------------
# ICS sync
# ---------------------------------------------------------------------------

async def _sync_ical_source(db: AsyncSession, source: CalendarIcalSource, default_reminder_minutes: int = 15) -> int:
    """Fetch a static ICS URL and upsert events."""
    try:
        import httpx
        from icalendar import Calendar
    except ImportError:
        logger.warning("[Calendar] icalendar not installed, skipping sync")
        source.last_sync_status = "error"
        source.last_error = "icalendar package not installed"
        await db.commit()
        return 0

    # Fetch ICS
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(source.url)
        resp.raise_for_status()

    cal = Calendar.from_ical(resp.text)
    vevents = list(cal.walk("VEVENT"))

    return await _upsert_events(db, source, vevents, default_reminder_minutes)


# ---------------------------------------------------------------------------
# CalDAV sync (企业微信)
# ---------------------------------------------------------------------------

async def _sync_caldav_source(db: AsyncSession, source: CalendarIcalSource, default_reminder_minutes: int = 15) -> int:
    """Sync via CalDAV protocol.

    企业微信 CalDAV note: the REPORT/calendar-query response only returns
    etags for ICS files, not inline ``calendar-data``.  We therefore:
    1. PROPFIND → discover calendar collections
    2. REPORT on each calendar → list .ics file URLs
    3. GET each .ics → parse VEVENT → upsert
    """
    try:
        import httpx
        from icalendar import Calendar
    except ImportError:
        logger.warning("[Calendar] httpx/icalendar not installed, skipping CalDAV sync")
        source.last_sync_status = "error"
        source.last_error = "httpx/icalendar not installed"
        await db.commit()
        return 0

    now = datetime.datetime.now()
    lookback = now - datetime.timedelta(days=source.lookback_days)
    lookahead = now + datetime.timedelta(days=source.lookahead_days)
    lookback_naive = lookback.replace(tzinfo=None)
    lookahead_naive = lookahead.replace(tzinfo=None)
    lookback_str = lookback_naive.strftime("%Y%m%dT000000Z")
    lookahead_str = lookahead_naive.strftime("%Y%m%dT235959Z")

    def _fetch():
        """Synchronous CalDAV fetch — runs in thread pool."""
        import base64
        import re

        # Fix URL
        url = source.url.strip()
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        if "caldav.wecom.work" in url and "/calendar" not in url:
            url = url.rstrip("/") + "/calendar/"

        base_url = url.rstrip("/")
        # Extract scheme+host for href construction (hrefs are absolute paths)
        scheme_host = re.match(r"(https?://[^/]+)", url) 
        scheme_host_str = scheme_host.group(1) if scheme_host else base_url
        username = source.caldav_username or ""
        password = source.caldav_password or ""
        creds_b64 = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers = {"Authorization": f"Basic {creds_b64}", "Content-Type": "application/xml; charset=utf-8"}

        with httpx.Client(timeout=15, verify=True) as c:
            # Step 1: PROPFIND → discover calendar collections
            propfind_body = (
                '<?xml version="1.0" encoding="utf-8"?>'
                "<A:propfind xmlns:A='DAV:'>"
                "<A:prop><A:displayname/><A:resourcetype/></A:prop>"
                "</A:propfind>"
            )
            resp = c.request("PROPFIND", url, headers={**headers, "Depth": "1"}, content=propfind_body)
            resp.raise_for_status()

            # Find calendar URLs (resourcetype contains <B:calendar />)
            cal_urls = set()
            # Split by <A:response> blocks to keep href & resourcetype together
            blocks = re.split(r"</?A:response>", resp.text)
            for block in blocks:
                if "<B:calendar" not in block:
                    continue
                href_m = re.search(r"<A:href>([^<]+)</A:href>", block)
                if href_m and "/" in href_m.group(1):
                    cal_urls.add(href_m.group(1))

            if not cal_urls:
                # Fallback: find paths ending with digits/ (calendar IDs)
                cal_urls = set(re.findall(r"<\w+:href>([^<]+/\d+/)</\w+:href>", resp.text))

            if not cal_urls:
                logger.warning("[Calendar] No calendar collections found at %s", url)
                return []

            logger.info("[Calendar] Found %d calendar(s) at %s", len(cal_urls), url)

            # Step 2: REPORT on each calendar → list .ics files using
            # namespace-agnostic pattern (response may use A:, D: or other prefixes)
            report_body = (
                b'<?xml version="1.0" encoding="utf-8"?>'
                b"<C:calendar-query xmlns:C='urn:ietf:params:xml:ns:caldav'>"
                b"<A:prop xmlns:A='DAV:'><A:getetag/></A:prop>"
                b"<C:filter><C:comp-filter name='VCALENDAR'>"
                b"<C:comp-filter name='VEVENT'>"
                b"<C:time-range start='%s' end='%s'/>"
                b"</C:comp-filter></C:comp-filter></C:filter>"
                b"</C:calendar-query>"
            ) % (lookback_str.encode(), lookahead_str.encode())

            ics_urls = []
            for cal_url in cal_urls:
                full_cal_url = f"{scheme_host_str}{cal_url}"
                try:
                    resp = c.request("REPORT", full_cal_url, headers={**headers, "Depth": "1"}, content=report_body)
                    if resp.status_code != 207:
                        continue
                    # Find .ics hrefs (namespace-agnostic)
                    for ics_href in re.findall(r"<\w+:href>([^<]+\.ics)</\w+:href>", resp.text):
                        ics_urls.append(ics_href)
                except Exception as e:
                    logger.debug("[Calendar] REPORT failed for %s: %s", full_cal_url, e)

            # Step 3: GET each .ics → parse VEVENT
            all_vevents = []
            for ics_path in ics_urls:
                ics_url = f"{scheme_host_str}{ics_path}"
                try:
                    resp = c.get(ics_url, headers={"Authorization": f"Basic {creds_b64}"}, timeout=10)
                    if resp.status_code != 200:
                        continue
                    vcal = Calendar.from_ical(resp.text)
                    all_vevents.extend(vcal.walk("VEVENT"))
                except Exception as e:
                    logger.debug("[Calendar] GET .ics failed for %s: %s", ics_url, e)

            logger.info(
                "[Calendar] CalDAV fetch complete: %d .ics files, %d VEVENTs",
                len(ics_urls),
                len(all_vevents),
            )
            return all_vevents

    try:
        vevents = await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=60.0)
    except asyncio.TimeoutError:
        raise RuntimeError("CalDAV 同步超时 (60s)") from None
    except Exception as e:
        err_msg = str(e).lower()
        if "auth" in err_msg or "401" in err_msg or "403" in err_msg or "unauthorized" in err_msg:
            raise RuntimeError("CalDAV 认证失败，请在企业微信重新获取密码并更新配置") from e
        raise

    return await _upsert_events(db, source, vevents, default_reminder_minutes)


# ---------------------------------------------------------------------------
# Shared upsert logic
# ---------------------------------------------------------------------------

async def _upsert_events(
    db: AsyncSession,
    source: CalendarIcalSource,
    vevents: list,
    default_reminder_minutes: int = 15,
) -> int:
    """Upsert VEVENT components into calendar_events table.

    Args:
        vevents: list of icalendar.VEvent components

    Returns:
        Number of events synced.
    """
    now = datetime.datetime.now()
    lookback = now - datetime.timedelta(days=source.lookback_days)
    lookahead = now + datetime.timedelta(days=source.lookahead_days)
    # Compare using naive datetimes (VEVENT may be offset-aware)
    lookback_naive = lookback.replace(tzinfo=None)
    lookahead_naive = lookahead.replace(tzinfo=None)

    synced = 0
    for component in vevents:
        uid = str(component.get("uid", ""))
        summary = str(component.get("summary", "(无标题)"))
        location_val = component.get("location")
        location = str(location_val) if location_val else ""
        desc_val = component.get("description")
        description = str(desc_val) if desc_val else ""

        dtstart_val = component.get("dtstart")
        dtend_val = component.get("dtend")
        if not dtstart_val:
            continue

        dtstart = dtstart_val.dt
        dtend = dtend_val.dt if dtend_val else None

        # Normalize date to datetime
        all_day = False
        if isinstance(dtstart, datetime.date) and not isinstance(dtstart, datetime.datetime):
            dtstart = datetime.datetime.combine(dtstart, datetime.time.min)
            all_day = True
        if dtend and isinstance(dtend, datetime.date) and not isinstance(dtend, datetime.datetime):
            dtend = datetime.datetime.combine(dtend, datetime.time.min)

        # Time range filter — strip timezone for naive comparison
        dtstart_naive = dtstart.replace(tzinfo=None) if hasattr(dtstart, 'tzinfo') and dtstart.tzinfo else dtstart
        if dtstart_naive < lookback_naive or dtstart_naive > lookahead_naive:
            continue

        # Upsert by ical_uid + source_id
        existing = None
        if uid:
            existing_result = await db.execute(
                select(CalendarEvent).where(
                    CalendarEvent.ical_uid == uid,
                    CalendarEvent.ical_source_id == source.id,
                )
            )
            existing = existing_result.scalar_one_or_none()

        if existing:
            existing.title = summary
            existing.description = description
            existing.start_time = dtstart
            existing.end_time = dtend
            existing.all_day = all_day
            existing.location = location
            existing.updated_at = now
        else:
            event = CalendarEvent(
                user_id=source.user_id,
                title=summary,
                description=description,
                start_time=dtstart,
                end_time=dtend,
                all_day=all_day,
                type="external",
                source=source.source_type,
                location=location,
                ical_uid=uid,
                ical_source_id=source.id,
                reminder_minutes=default_reminder_minutes,
            )
            db.add(event)
        synced += 1

    # Update sync metadata
    source.last_sync_at = now
    source.last_sync_status = "ok"
    source.last_error = ""
    source.sync_event_count = synced
    await db.commit()

    logger.info(
        "[Calendar] Synced %d events from %s (%s)",
        synced,
        source.name,
        source.source_type,
    )
    return synced

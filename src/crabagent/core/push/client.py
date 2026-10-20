"""HTTP clients for push providers (Bark / ntfy).

Both clients are stateless: one POST per notification, no session kept.
Failures raise :class:`PushError` so callers can log and continue.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0)


class PushError(RuntimeError):
    """Raised when a push provider rejects or fails a notification."""


@dataclass
class PushPayload:
    title: str
    body: str = ""
    url: str = ""  # deep link opened when the notification is tapped
    category: str = ""  # task_done | task_waiting | scheduled_task | email ...
    sound: str = ""
    time_sensitive: bool = True


async def send_bark(
    server: str,
    device_key: str,
    payload: PushPayload,
) -> bool:
    """Send via Bark (iOS APNs). Docs: https://bark.day.app/#/tutorial"""
    if not device_key:
        raise PushError("bark_device_key is empty")
    base = (server or "https://api.day.app").rstrip("/")

    body: dict[str, object] = {
        "device_key": device_key,
        "title": payload.title[:200],
        "body": payload.body[:2000],
        "group": "CrabAgent",
    }
    if payload.sound:
        body["sound"] = payload.sound
    if payload.url:
        body["url"] = payload.url
    # timeSensitive lets waiting-for-user notifications break through Focus.
    # Scheduled results use "active"; everything else is passive.
    if payload.time_sensitive and payload.category in ("task_waiting",):
        body["level"] = "timeSensitive"
    else:
        body["level"] = "active"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(f"{base}/push", json=body)
    except httpx.HTTPError as e:
        raise PushError(f"bark request failed: {e}") from e

    if resp.status_code != 200:
        raise PushError(f"bark returned HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if isinstance(data, dict) and data.get("code") not in (200, None):
        raise PushError(f"bark error: {data.get('message', data)}")
    return True


async def send_ntfy(
    server: str,
    topic: str,
    payload: PushPayload,
) -> bool:
    """Send via ntfy. Docs: https://docs.ntfy.sh/publish/"""
    if not topic:
        raise PushError("ntfy_topic is empty")
    base = (server or "https://ntfy.sh").rstrip("/")

    headers = {
        "Title": payload.title[:200],
        "Tags": "crab",
        "Priority": "high" if payload.category == "task_waiting" else "default",
    }
    if payload.url:
        headers["Click"] = payload.url

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(f"{base}/{topic}", content=payload.body[:2000], headers=headers)
    except httpx.HTTPError as e:
        raise PushError(f"ntfy request failed: {e}") from e

    if resp.status_code >= 300:
        raise PushError(f"ntfy returned HTTP {resp.status_code}: {resp.text[:200]}")
    return True

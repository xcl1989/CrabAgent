"""Trusted work system: persistent TaskRequest service.

A TaskRequest is any point where the agent needs the user: missing input,
a choice between options, approval of a risky action, a human-only step
(login/MFA), or a result review.

Guarantees (Phase 2):

- persistence: requests survive restarts; the DB is the source of truth
  and in-process Futures are only a live bridge;
- one-shot: an external action is authorized at most once per request;
- idempotent decisions: re-submitting a decided request returns the
  recorded outcome without re-executing side effects;
- expirable: stale requests flip to ``expired`` and must not be used.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import TaskRequest

logger = logging.getLogger(__name__)

REQUEST_TYPES = ("input", "choice", "approval", "human_step", "review")
RISK_LEVELS = ("low", "medium", "high", "critical")

# request_key → live Future for the process that created the request.
# Empty after a restart; decisions then only update the database.
_live_futures: dict[str, asyncio.Future] = {}


def _now() -> datetime.datetime:
    return datetime.datetime.now()


def new_request_key(prefix: str = "req") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def register_live_future(request_key: str, future: asyncio.Future) -> None:
    """Bridge a persistent request to the Future the agent loop awaits."""
    _live_futures[request_key] = future


def drop_live_future(request_key: str) -> asyncio.Future | None:
    return _live_futures.pop(request_key, None)


def _request_to_dict(r: TaskRequest) -> dict:
    return {
        "id": r.id,
        "request_key": r.request_key,
        "user_id": r.user_id,
        "task_id": r.task_id,
        "run_id": r.run_id,
        "session_id": r.session_id,
        "request_type": r.request_type,
        "operation": r.operation,
        "title": r.title,
        "description": r.description,
        "question": r.question,
        "options": r.options,
        "risk_level": r.risk_level,
        "display_payload": r.display_payload,
        "resource_version": r.resource_version,
        "status": r.status,
        "decision_note": r.decision_note,
        "expires_at": r.expires_at.isoformat() if r.expires_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        "consumed_at": r.consumed_at.isoformat() if r.consumed_at else None,
    }


async def create_request(
    db: AsyncSession,
    user_id: int,
    request_type: str,
    title: str = "",
    session_id: str = "",
    task_id: int | None = None,
    run_id: int | None = None,
    operation: str = "",
    description: str = "",
    question: str = "",
    options: list | None = None,
    risk_level: str = "low",
    display_payload: dict | None = None,
    resume_action: str = "",
    resume_ref: str = "",
    resource_version: str = "",
    expires_at: datetime.datetime | None = None,
    request_key: str = "",
) -> dict:
    if request_type not in REQUEST_TYPES:
        raise ValueError(f"Invalid request type {request_type!r}; expected one of {REQUEST_TYPES}")
    if risk_level not in RISK_LEVELS:
        raise ValueError(f"Invalid risk level {risk_level!r}; expected one of {RISK_LEVELS}")

    key = request_key or new_request_key()
    row = TaskRequest(
        request_key=key,
        user_id=user_id,
        task_id=task_id,
        run_id=run_id,
        session_id=session_id,
        request_type=request_type,
        operation=operation[:100],
        title=(title or question or operation or request_type)[:500],
        description=description,
        question=question,
        options=options,
        risk_level=risk_level,
        display_payload=display_payload,
        resume_action=resume_action[:100],
        resume_ref=resume_ref[:500],
        resource_version=resource_version[:200],
        status="pending",
        expires_at=expires_at,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _request_to_dict(row)


async def get_request(db: AsyncSession, request_key: str, user_id: int) -> dict | None:
    result = await db.execute(
        select(TaskRequest).where(TaskRequest.request_key == request_key, TaskRequest.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    return _request_to_dict(row) if row else None


async def list_pending_requests(db: AsyncSession, user_id: int, session_id: str = "") -> list[dict]:
    stmt = (
        select(TaskRequest)
        .where(TaskRequest.user_id == user_id, TaskRequest.status == "pending")
        .order_by(TaskRequest.created_at.desc())
    )
    if session_id:
        stmt = stmt.where(TaskRequest.session_id == session_id)
    result = await db.execute(stmt)
    return [_request_to_dict(r) for r in result.scalars().all()]


async def decide_request(
    db: AsyncSession,
    request_key: str,
    user_id: int,
    decision: str,
    answer: str = "",
    note: str = "",
) -> dict:
    """Apply a user decision to a request.

    ``decision`` is one of: approve, reject, answer, cancel.
    Idempotent: when the request was already decided/consumed the stored
    state is returned unchanged and no Future is resolved twice.

    Returns the request dict with an extra ``future_resolved`` flag that
    tells callers whether the originating agent process was still alive.
    """
    if decision not in ("approve", "reject", "answer", "cancel"):
        raise ValueError("decision must be one of approve/reject/answer/cancel")

    result = await db.execute(
        select(TaskRequest).where(TaskRequest.request_key == request_key, TaskRequest.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise LookupError(f"TaskRequest {request_key} not found")

    future_resolved = False

    if row.status != "pending":
        # Idempotent replay: return the recorded outcome untouched.
        payload = _request_to_dict(row)
        payload["future_resolved"] = future_resolved
        return payload

    now = _now()
    if row.expires_at and row.expires_at < now:
        row.status = "expired"
        row.decided_at = now
        await db.commit()
        payload = _request_to_dict(row)
        payload["future_resolved"] = future_resolved
        return payload

    if decision == "approve":
        row.status = "approved"
    elif decision in ("reject", "cancel"):
        row.status = "rejected" if decision == "reject" else "cancelled"
    elif decision == "answer":
        if not answer:
            raise ValueError("answer is required for decision='answer'")
        row.status = "approved"
        row.decision_note = answer
    if note and decision != "answer":
        row.decision_note = note[:1000]
    row.decided_at = now

    await db.commit()

    # Resolve the live bridge (if the originating process still waits).
    future = drop_live_future(request_key)
    if future is not None and not future.done():
        try:
            if row.request_type in ("input", "choice"):
                future.set_result(answer)
            else:
                future.set_result(row.status == "approved")
            future_resolved = True
        except asyncio.InvalidStateError:
            future_resolved = False

    payload = _request_to_dict(row)
    payload["future_resolved"] = future_resolved
    return payload


async def consume_request(db: AsyncSession, request_key: str, user_id: int) -> dict | None:
    """Mark an approved request as consumed by the actual external action.

    Idempotent: consuming twice returns the stored state without error,
    but only the first call stamps ``consumed_at``.
    """
    result = await db.execute(
        select(TaskRequest).where(TaskRequest.request_key == request_key, TaskRequest.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    if row.status == "approved" and not row.consumed_at:
        row.status = "consumed"
        row.consumed_at = _now()
        await db.commit()
    return _request_to_dict(row)


async def expire_stale_requests(db: AsyncSession, user_id: int | None = None) -> int:
    """Flip pending requests past their expiry to ``expired``."""
    now = _now()
    stmt = select(TaskRequest).where(
        TaskRequest.status == "pending",
        TaskRequest.expires_at.isnot(None),
        TaskRequest.expires_at < now,
    )
    if user_id is not None:
        stmt = stmt.where(TaskRequest.user_id == user_id)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    for row in rows:
        row.status = "expired"
        row.decided_at = now
    if rows:
        await db.commit()
    return len(rows)

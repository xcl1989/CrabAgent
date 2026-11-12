from __future__ import annotations

import asyncio
import time
from collections import deque
from types import SimpleNamespace

from starlette.concurrency import run_in_threadpool

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, StrictBool, SecretStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.agent import background, background_group, background_outbox, semantic_summary
from crabagent.core import database as models
from sqlalchemy import select
from crabagent.core.database import User, get_db
from crabagent.serve.deps import get_current_user, get_owned_conversation

router = APIRouter(prefix="/sessions/{session_id}/background-tasks", tags=["background-tasks"])


async def _context(session_id: str, branch: str | None, user: User, db: AsyncSession):
    conv = await get_owned_conversation(db, session_id, user)
    if branch is not None and branch != conv.active_branch:
        raise HTTPException(status_code=409, detail="Active branch changed")
    return SimpleNamespace(metadata={"user_id": user.id, "session_id": session_id, "branch_id": conv.active_branch}, provider_name=conv.provider, model=conv.model)


@router.get("")
async def list_tasks(
    session_id: str, response: Response, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    context = await _context(session_id, None, user, db)
    response.headers["Cache-Control"] = "no-store"
    try:
        tasks = await background.list_tasks(context)
    except ValueError:
        raise HTTPException(status_code=409, detail="Active branch changed") from None
    return {"branch": context.metadata["branch_id"], "tasks": tasks}


@router.get("/groups")
async def list_groups(
    session_id: str, response: Response, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    context = await _context(session_id, None, user, db)
    response.headers["Cache-Control"] = "no-store"
    try:
        groups = await background_group.list_groups(context)
    except ValueError:
        raise HTTPException(status_code=409, detail="Active branch changed") from None
    return {"branch": context.metadata["branch_id"], "groups": groups}


class DeliveryConsent(BaseModel):
    consent: StrictBool


def _delivery_scope(context):
    return tuple(context.metadata[key] for key in ("user_id", "session_id", "branch_id"))


@router.get("/deliveries")
async def list_deliveries(session_id: str, response: Response, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    context = await _context(session_id, None, user, db)
    response.headers["Cache-Control"] = "no-store"
    await background._recover_if_available()
    scope = _delivery_scope(context)
    rows = (await db.scalars(select(models.BackgroundDelivery).where(
        models.BackgroundDelivery.user_id == scope[0], models.BackgroundDelivery.session_id == scope[1],
        models.BackgroundDelivery.branch_id == scope[2], models.BackgroundDelivery.status == "ready",
        select(models.Conversation.id).where(models.Conversation.user_id == scope[0],
            models.Conversation.session_id == scope[1], models.Conversation.active_branch == scope[2]).exists(),
    ).order_by(models.BackgroundDelivery.created_at.desc()).limit(100))).all()
    cards = []
    for row in rows:
        steps = (await db.scalars(select(models.BackgroundGroupStep).where(
            models.BackgroundGroupStep.group_id == row.group_id).order_by(models.BackgroundGroupStep.step_id))).all()
        cards.append({"id": row.group_id, "status": row.terminal_status,
                      "steps": [{"step_id": step.step_id, "status": step.status, "result": step.result} for step in steps]})
    return {"branch": scope[2], "deliveries": cards}


@router.post("/groups/{group_id}/delivery")
async def authorize_delivery(session_id: str, group_id: str, consent: DeliveryConsent, response: Response, branch: str = Query(..., min_length=1), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    context = await _context(session_id, branch, user, db)
    response.headers["Cache-Control"] = "no-store"
    if not consent.consent:
        raise HTTPException(status_code=400, detail="Explicit consent required")
    try:
        await background_outbox.authorize(db, group_id, _delivery_scope(context))
        await db.commit()
    except (ValueError, IntegrityError):
        await db.rollback()
        raise HTTPException(status_code=409, detail="Delivery authorization unavailable") from None
    return {"authorized": True}


@router.delete("/groups/{group_id}/delivery")
async def revoke_delivery(session_id: str, group_id: str, response: Response, branch: str = Query(..., min_length=1), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    context = await _context(session_id, branch, user, db)
    response.headers["Cache-Control"] = "no-store"
    revoked = await background_outbox.revoke(db, group_id, _delivery_scope(context))
    await db.commit()
    return {"revoked": revoked}


@router.get("/groups/{group_id}")
async def get_group(
    session_id: str, group_id: str, response: Response, branch: str = Query(..., min_length=1),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    context = await _context(session_id, branch, user, db)
    response.headers["Cache-Control"] = "no-store"
    try:
        return await background_group.get(context, group_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Group unavailable") from None


@router.post("/groups/{group_id}/cancel")
async def cancel_group(
    session_id: str, group_id: str, response: Response, branch: str = Query(..., min_length=1),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    context = await _context(session_id, branch, user, db)
    response.headers["Cache-Control"] = "no-store"
    try:
        return await background_group.cancel(context, group_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Group unavailable") from None


class SummaryConsent(BaseModel):
    consent: StrictBool
    password: SecretStr
    binding: str


_attempts: dict[int, deque[float]] = {}
_verify_slots = asyncio.Semaphore(4)


def _reserve_attempt(user_id: int):
    now = time.monotonic()
    for key, timestamps in list(_attempts.items()):
        while timestamps and timestamps[0] <= now - 300:
            timestamps.popleft()
        if not timestamps:
            _attempts.pop(key, None)
    attempts = _attempts.setdefault(user_id, deque())
    if len(attempts) >= 5:
        raise HTTPException(status_code=429, detail="Too many reauthentication attempts", headers={"Retry-After": "300"})
    attempts.append(now)


@router.get("/groups/{group_id}/semantic-summary")
async def get_semantic_summary(session_id: str, group_id: str, response: Response, branch: str = Query(..., min_length=1), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    context = await _context(session_id, branch, user, db)
    response.headers["Cache-Control"] = "no-store"
    try:
        return {"summary": await semantic_summary.get(context, group_id)}
    except ValueError:
        raise HTTPException(status_code=404, detail="Group unavailable") from None


@router.get("/groups/{group_id}/semantic-summary/provider")
async def summary_provider(session_id: str, group_id: str, response: Response, branch: str = Query(..., min_length=1), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    context = await _context(session_id, branch, user, db)
    response.headers["Cache-Control"] = "no-store"
    try:
        await semantic_summary.get(context, group_id)
        _, identity = await semantic_summary.provider_binding(context)
        return identity
    except ValueError:
        raise HTTPException(status_code=404, detail="Group or provider unavailable") from None


@router.post("/groups/{group_id}/semantic-summary")
async def start_semantic_summary(session_id: str, group_id: str, consent: SummaryConsent, response: Response, branch: str = Query(..., min_length=1), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from crabagent.core.auth_utils import verify_password

    context = await _context(session_id, branch, user, db)
    response.headers["Cache-Control"] = "no-store"
    if not consent.consent:
        raise HTTPException(status_code=400, detail="Explicit consent required")
    # Reauthentication is separate from the model-accessible tool contract.
    persisted = await db.get(User, user.id)
    _reserve_attempt(user.id)
    async with _verify_slots:
        verified = bool(persisted and persisted.enabled and await run_in_threadpool(verify_password, consent.password.get_secret_value(), persisted.password_hash))
    if not verified:
        raise HTTPException(status_code=403, detail="Reauthentication failed")
    try:
        await semantic_summary.get(context, group_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Group unavailable") from None
    try:
        return {"summary": await semantic_summary.start(context, group_id, user_consented_to_external_processing=True, binding=consent.binding)}
    except (ValueError, IntegrityError):
        raise HTTPException(status_code=409, detail="Summary cannot be started") from None


@router.delete("/groups/{group_id}/semantic-summary")
async def delete_semantic_summary(session_id: str, group_id: str, response: Response, branch: str = Query(..., min_length=1), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    context = await _context(session_id, branch, user, db)
    response.headers["Cache-Control"] = "no-store"
    try:
        deleted = await semantic_summary.delete(context, group_id)
        return {"deleted": deleted}
    except LookupError:
        raise HTTPException(status_code=404, detail="Group unavailable") from None
    except ValueError:
        raise HTTPException(status_code=409, detail="Summary is running") from None


@router.post("/groups/{group_id}/semantic-summary/cancel")
async def cancel_semantic_summary(session_id: str, group_id: str, response: Response, branch: str = Query(..., min_length=1), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    context = await _context(session_id, branch, user, db)
    response.headers["Cache-Control"] = "no-store"
    try:
        await semantic_summary.get(context, group_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Group unavailable") from None
    try:
        return {"summary": await semantic_summary.cancel(context, group_id)}
    except ValueError:
        raise HTTPException(status_code=409, detail="Cancellation unavailable in this process") from None


@router.get("/{job_id}")
async def get_task(
    session_id: str,
    job_id: str,
    response: Response,
    branch: str = Query(..., min_length=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    context = await _context(session_id, branch, user, db)
    response.headers["Cache-Control"] = "no-store"
    try:
        return await background.get(context, job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Task unavailable") from None


@router.post("/{job_id}/cancel")
async def cancel_task(
    session_id: str,
    job_id: str,
    response: Response,
    branch: str = Query(..., min_length=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    context = await _context(session_id, branch, user, db)
    response.headers["Cache-Control"] = "no-store"
    try:
        return await background.cancel(context, job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Task unavailable") from None

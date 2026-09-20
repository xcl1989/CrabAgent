from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import User, get_db
from crabagent.serve.deps import get_current_user

router = APIRouter(prefix="/task-requests", tags=["task-requests"])


class DecisionRequest(BaseModel):
    decision_token: str = ""  # reserved for stricter one-shot validation
    resource_version: str = ""
    answer: str = ""
    note: str = ""


@router.get("")
async def list_requests(
    status: str = "pending",
    session_id: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.task.request_service import list_pending_requests

    if status != "pending":
        raise HTTPException(status_code=400, detail="Only status=pending is supported for now")
    return {"requests": await list_pending_requests(db, user.id, session_id)}


@router.get("/{request_key}")
async def get_request(
    request_key: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.task.request_service import get_request as _get

    req = await _get(db, request_key, user.id)
    if not req:
        raise HTTPException(status_code=404, detail="Task request not found")
    return req


async def _decide(request_key: str, decision: str, req: DecisionRequest, user: User, db: AsyncSession):
    from crabagent.core.task.request_service import decide_request

    try:
        payload = await decide_request(db, request_key, user.id, decision, answer=req.answer, note=req.note)
    except LookupError:
        raise HTTPException(status_code=404, detail="Task request not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Resource version guard: the approved object changed → old request dies.
    if req.resource_version and payload.get("resource_version") and req.resource_version != payload["resource_version"]:
        raise HTTPException(
            status_code=409, detail="Resource changed since the request was created; please review again"
        )
    return payload


@router.post("/{request_key}/approve")
async def approve_request(
    request_key: str,
    req: DecisionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _decide(request_key, "approve", req, user, db)


@router.post("/{request_key}/reject")
async def reject_request(
    request_key: str,
    req: DecisionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _decide(request_key, "reject", req, user, db)


@router.post("/{request_key}/answer")
async def answer_request(
    request_key: str,
    req: DecisionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _decide(request_key, "answer", req, user, db)


@router.post("/{request_key}/cancel")
async def cancel_request(
    request_key: str,
    req: DecisionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _decide(request_key, "cancel", req, user, db)

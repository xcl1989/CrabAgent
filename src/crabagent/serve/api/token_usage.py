"""Token usage analytics API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from crabagent.core.database import (
    User,
    token_usage_overview,
    token_usage_session_detail,
    token_usage_sessions,
    token_usage_workspaces,
)
from crabagent.serve.deps import get_current_user

router = APIRouter(prefix="/token-usage", tags=["token-usage"])


@router.get("/overview")
async def get_overview(
    days: int = Query(30, ge=1, le=365, description="Lookback days (365 = all)"),
    workspace: str = Query("", description="Filter by workspace path"),
    user: User = Depends(get_current_user),
):
    """Overview: totals, cache hit rate, trend (daily/hourly), by-agent, by-model."""
    return await token_usage_overview(user.id, days=days, workspace=workspace)


@router.get("/sessions")
async def list_sessions_usage(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    workspace: str = Query("", description="Filter by workspace path"),
    user: User = Depends(get_current_user),
):
    """Per-session aggregated token usage."""
    sessions, total = await token_usage_sessions(user.id, limit=limit, offset=offset, workspace=workspace)
    return {"sessions": sessions, "total": total}


@router.get("/workspaces")
async def list_workspaces_usage(
    user: User = Depends(get_current_user),
):
    """List workspaces with token usage stats for the filter dropdown."""
    return await token_usage_workspaces(user.id)


@router.get("/sessions/{session_id}")
async def get_session_usage_detail(
    session_id: str,
    user: User = Depends(get_current_user),
):
    """Detailed per-iteration token usage for a single session."""
    detail = await token_usage_session_detail(user.id, session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="No token usage data for this session")
    return detail

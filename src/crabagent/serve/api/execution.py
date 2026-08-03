"""Execution span tree API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from crabagent.core.database import (
    get_session_runs,
    get_spans_by_run,
    get_spans_by_session,
)
from crabagent.core.observability.insights import analyze_spans, summarize_run
from crabagent.serve.deps import get_current_user

router = APIRouter(prefix="/execution", tags=["execution"])


def _build_tree(spans: list[dict]) -> list[dict]:
    """Build a nested tree from flat span list using parent_id."""
    by_parent: dict[int | None, list[dict]] = {}
    span_map: dict[int, dict] = {}

    for s in spans:
        sid = s["id"]
        node = {**s, "children": []}
        span_map[sid] = node
        pid = s.get("parent_id")
        by_parent.setdefault(pid, []).append(node)

    def _attach(nodes: list[dict]) -> list[dict]:
        for node in nodes:
            child_list = by_parent.get(node["id"], [])
            node["children"] = _attach(child_list)
        # Sort by seq within each level
        nodes.sort(key=lambda n: n.get("seq", 0))
        return nodes

    roots = by_parent.get(None, [])
    if roots:
        return _attach([dict(r) for r in roots])
    # Fallback: no explicit None parent — treat top-level spans as roots
    root_ids = {s["id"] for s in spans}
    child_ids = {s["parent_id"] for s in spans if s.get("parent_id") is not None}
    top_ids = root_ids - child_ids
    return _attach([span_map[sid] for sid in top_ids])


@router.get("/sessions/{session_id}/runs")
async def list_runs(
    session_id: str,
    user=Depends(get_current_user),
):
    """List all runs in a session with summary stats."""
    runs = await get_session_runs(session_id)
    return {"runs": runs}


@router.get("/sessions/{session_id}/spans")
async def list_session_spans(
    session_id: str,
    user=Depends(get_current_user),
):
    """Return all spans for a session as a flat list, grouped by run_id."""
    spans = await get_spans_by_session(session_id)
    runs: dict[str, list[dict]] = {}
    for s in spans:
        runs.setdefault(s["run_id"], []).append(s)
    trees = {run_id: _build_tree(run_spans) for run_id, run_spans in runs.items()}
    return {"session_id": session_id, "runs": list(runs.keys()), "trees": trees}


@router.get("/sessions/{session_id}/runs/{run_id}/spans")
async def list_run_spans(
    session_id: str,
    run_id: str,
    user=Depends(get_current_user),
):
    """Return spans for a specific run as a tree."""
    spans = await get_spans_by_run(session_id, run_id)
    if not spans:
        raise HTTPException(status_code=404, detail="No spans found for this run")
    tree = _build_tree(spans)
    return {"session_id": session_id, "run_id": run_id, "tree": tree, "span_count": len(spans)}


@router.get("/sessions/{session_id}/runs/{run_id}/insights")
async def get_run_insights(
    session_id: str,
    run_id: str,
    user=Depends(get_current_user),
):
    """Return automated insights for a specific run."""
    spans = await get_spans_by_run(session_id, run_id)
    if not spans:
        raise HTTPException(status_code=404, detail="No spans found for this run")
    summary = summarize_run(spans)
    return {
        "session_id": session_id,
        "run_id": run_id,
        "summary": summary,
        "insights": summary.pop("insights", []),
    }


@router.get("/sessions/{session_id}/insights")
async def get_session_insights(
    session_id: str,
    user=Depends(get_current_user),
):
    """Return insights for all runs in a session."""
    spans = await get_spans_by_session(session_id)
    if not spans:
        return {"session_id": session_id, "insights": []}

    # Group by run_id
    runs: dict[str, list[dict]] = {}
    for s in spans:
        runs.setdefault(s["run_id"], []).append(s)

    all_insights = []
    for run_id, run_spans in runs.items():
        run_insights = analyze_spans(run_spans)
        for insight in run_insights:
            insight["run_id"] = run_id
            all_insights.append(insight)

    # Sort: errors first, then warnings, then info
    severity_order = {"error": 0, "warning": 1, "info": 2}
    all_insights.sort(key=lambda i: severity_order.get(i.get("severity", "info"), 3))

    return {"session_id": session_id, "insights": all_insights}

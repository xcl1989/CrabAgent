"""Lightweight execution span helpers for the agent loop.

These functions collect structured span data during an agent run.
Spans are stored in-memory on AgentContext and flushed to the
``execution_spans`` table after the run completes.

Span types:
  - ``llm_call``: A single LLM inference call (one litellm.acompletion).
  - ``tool_call``: A single tool execution.
  - ``agent_delegate``: A sub-agent delegation (spawn_sub_agent).
  - ``compress``: Context compression event.
  - ``agent_run``: The root span for a full run_agent invocation.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from crabagent.core.agent.context import AgentContext

logger = logging.getLogger(__name__)


def start_span(
    ctx: AgentContext,
    span_type: str,
    name: str,
    parent_id: int | None = None,
    source: str = "",
    provider: str = "",
) -> dict[str, Any]:
    """Create and register a new span on the context.

    Args:
        ctx: The AgentContext to attach the span to.
        span_type: One of ``llm_call``, ``tool_call``, ``agent_delegate``,
            ``compress``, ``agent_run``.
        name: Human-readable name (model name, tool name, agent name).
        parent_id: Parent span's local ID (the ``_id`` field), or None for root.
        source: Tool source (``builtin``, ``mcp``, ``custom``).
        provider: LLM provider name for llm_call spans (e.g. ``ZAI``, ``openai``).

    Returns:
        The span dict, which should be passed to :func:`end_span` when done.
    """
    ctx._span_counter += 1
    span: dict[str, Any] = {
        "_id": ctx._span_counter,
        "parent_id": parent_id,
        "seq": _count_children(ctx, parent_id),
        "span_type": span_type,
        "name": name,
        "agent_name": ctx.current_agent,
        "source": source,
        "provider": provider,
        "started_at": time.time(),
        "duration_ms": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cached_tokens": 0,
        "reasoning_tokens": 0,
        "status": "ok",
        "summary": "",
        "error": "",
    }
    ctx.spans.append(span)
    return span


def end_span(span: dict[str, Any], **attrs: Any) -> None:
    """Finalise a span: compute duration and merge extra attributes."""
    span["duration_ms"] = int((time.time() - span["started_at"]) * 1000)
    span.update(attrs)


def _count_children(ctx: AgentContext, parent_id: int | None) -> int:
    """Count how many spans already share this parent."""
    return sum(1 for s in ctx.spans if s.get("parent_id") == parent_id)


def export_spans(ctx: AgentContext) -> list[dict[str, Any]]:
    """Return spans in a format suitable for DB persistence.

    The ``_id`` field is kept so that :func:`execution_span_batch_create`
    can map in-memory IDs to database IDs and fix ``parent_id`` references.
    """
    return [dict(s) for s in ctx.spans]

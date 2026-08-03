"""Automated insight analysis for execution spans.

After a run completes, this module analyses the span tree to detect:
  - Tool call loops (same tool called many times)
  - Token hotspots (one LLM call dominates token usage)
  - Context bloat (prompt tokens growing rapidly across iterations)
  - Error concentration (multiple failed tool calls)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def analyze_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Analyze a flat list of spans from a single run and return insights.

    Args:
        spans: Flat list of span dicts (same format as DB rows).

    Returns:
        List of insight dicts with keys: type, severity, title, detail, span_ids.
    """
    if not spans:
        return []

    insights: list[dict[str, Any]] = []

    # Separate by type
    llm_spans = [s for s in spans if s.get("span_type") == "llm_call"]
    tool_spans = [s for s in spans if s.get("span_type") == "tool_call"]

    # ── 1. Tool call loop detection ──
    tool_counts: dict[str, list[dict]] = {}
    for s in tool_spans:
        name = s.get("name", "")
        tool_counts.setdefault(name, []).append(s)

    for name, group in tool_counts.items():
        if len(group) >= 5:
            insights.append({
                "type": "tool_loop",
                "severity": "warning",
                "title": f"工具 '{name}' 被调用了 {len(group)} 次",
                "detail": (
                    "Agent 可能在循环中反复调用同一工具。"
                    "考虑优化 prompt 或增加终止条件。"
                ),
                "span_ids": [s["id"] for s in group if "id" in s],
            })

    # ── 2. Token hotspot: one LLM call dominates prompt token usage ──
    if llm_spans:
        total_prompt = sum(s.get("prompt_tokens", 0) for s in llm_spans)
        if total_prompt > 0:
            max_span = max(llm_spans, key=lambda s: s.get("prompt_tokens", 0))
            max_prompt = max_span.get("prompt_tokens", 0)
            if max_prompt > total_prompt * 0.6 and max_prompt > 1000:
                pct = round(max_prompt / total_prompt * 100) if total_prompt else 0
                insights.append({
                    "type": "token_hotspot",
                    "severity": "info",
                    "title": (
                        f"单次 LLM 调用消耗 {max_prompt:,} prompt tokens"
                        f"（占总量 {pct}%）"
                    ),
                    "detail": (
                        "上下文可能累积过长。"
                        "考虑启用上下文压缩或拆分任务以减少单次调用成本。"
                    ),
                    "span_id": max_span.get("id"),
                })

    # ── 3. Context bloat: prompt tokens growing rapidly ──
    if len(llm_spans) >= 3:
        sorted_llm = sorted(llm_spans, key=lambda s: s.get("seq", 0))
        prompts = [s.get("prompt_tokens", 0) for s in sorted_llm]
        # Check if growth rate exceeds 30% per iteration
        growing = True
        for i in range(len(prompts) - 1):
            if prompts[i] == 0 or prompts[i + 1] < prompts[i] * 1.3:
                growing = False
                break
        if growing and prompts[0] > 0:
            growth = round(prompts[-1] / prompts[0], 1) if prompts[0] else 0
            insights.append({
                "type": "context_bloat",
                "severity": "warning",
                "title": "上下文快速膨胀",
                "detail": (
                    f"Prompt tokens 从 {prompts[0]:,} 增长到 "
                    f"{prompts[-1]:,}（{len(prompts)} 轮，"
                    f"约 {growth}x 增长）。"
                ),
            })

    # ── 4. Error concentration ──
    error_tools = [s for s in tool_spans if s.get("status") == "error"]
    if error_tools:
        error_names = {}
        for s in error_tools:
            name = s.get("name", "unknown")
            error_names[name] = error_names.get(name, 0) + 1
        detail_parts = [f"{name}: {count}次" for name, count in list(error_names.items())[:3]]
        insights.append({
            "type": "tool_errors",
            "severity": "error",
            "title": f"{len(error_tools)} 次工具调用失败",
            "detail": "; ".join(detail_parts),
            "span_ids": [s["id"] for s in error_tools if "id" in s],
        })

    # ── 5. Slow tool calls ──
    slow_tools = [s for s in tool_spans if s.get("duration_ms", 0) > 30_000]
    if slow_tools:
        slow_names = {}
        for s in slow_tools:
            name = s.get("name", "unknown")
            old = slow_names.get(name, 0)
            slow_names[name] = max(old, s.get("duration_ms", 0))
        detail_parts = [
            f"{name}: {ms/1000:.0f}s" for name, ms in list(slow_names.items())[:3]
        ]
        insights.append({
            "type": "slow_tools",
            "severity": "info",
            "title": f"{len(slow_tools)} 次工具调用超过 30 秒",
            "detail": "; ".join(detail_parts),
            "span_ids": [s["id"] for s in slow_tools if "id" in s],
        })

    return insights


def summarize_run(spans: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a quick summary of a run from its spans."""
    if not spans:
        return {"total_spans": 0}

    llm_spans = [s for s in spans if s.get("span_type") == "llm_call"]
    tool_spans = [s for s in spans if s.get("span_type") == "tool_call"]
    delegate_spans = [s for s in spans if s.get("span_type") == "agent_delegate"]

    total_prompt = sum(s.get("prompt_tokens", 0) for s in llm_spans)
    total_completion = sum(s.get("completion_tokens", 0) for s in llm_spans)
    total_cached = sum(s.get("cached_tokens", 0) for s in llm_spans)
    total_reasoning = sum(s.get("reasoning_tokens", 0) for s in llm_spans)
    total_duration = sum(s.get("duration_ms", 0) for s in spans)
    error_count = sum(1 for s in spans if s.get("status") == "error")

    return {
        "total_spans": len(spans),
        "llm_calls": len(llm_spans),
        "tool_calls": len(tool_spans),
        "delegations": len(delegate_spans),
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
        "cached_tokens": total_cached,
        "reasoning_tokens": total_reasoning,
        "total_tokens": total_prompt + total_completion,
        "total_duration_ms": total_duration,
        "error_count": error_count,
        "insights": analyze_spans(spans),
    }

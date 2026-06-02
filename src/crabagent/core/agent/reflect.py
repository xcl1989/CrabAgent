"""Long-term memory extraction utilities.

Moved out of :mod:`crabagent.core.agent.agents` so that both sub-agent
delegation and the main-loop ``ReflectMiddleware`` can share the same
reflection logic without circular imports.

Public surface:
- :func:`classify_task` — keyword-based task category tagging
- :func:`rule_extract_lesson` — deterministic lesson (high iterations etc.)
- :func:`llm_reflect_lesson` — single LLM call to extract one technical lesson
- :func:`llm_extract_user_preferences` — single LLM call to extract user
  preferences / behavioural rules (Lobehub-style "Memory")
- :func:`persist_lesson` — write a lesson dict into ``AgentMemory``
- :func:`persist_preferences` — write preference dicts into ``AgentMemory``
"""

from __future__ import annotations

import logging
import time
from typing import Any

import litellm

from crabagent.core.provider_store import get_default_provider, get_provider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Task classification (kept identical to agents.py for backward compat)
# ---------------------------------------------------------------------------


def classify_task(task: str) -> str:
    tl = task.lower()
    code_kw = [
        "code",
        "代码",
        "bug",
        "debug",
        "refactor",
        "重构",
        "implement",
        "实现",
        "function",
        "函数",
        "class",
        "api",
        "test",
        "测试",
        "write",
        "编写",
        "fix",
        "修复",
    ]
    research_kw = [
        "search",
        "搜索",
        "research",
        "调研",
        "find",
        "查找",
        "browse",
        "浏览",
        "scrape",
        "爬取",
        "look up",
        "查询",
    ]
    analysis_kw = [
        "analyze",
        "分析",
        "compare",
        "比较",
        "report",
        "报告",
        "review",
        "审查",
        "evaluate",
        "评估",
        "check",
        "检查",
    ]
    writing_kw = [
        "translate",
        "翻译",
        "edit",
        "编辑",
        "format",
        "格式化",
        "document",
        "文档",
        "content",
        "内容",
        "article",
        "文章",
        "write",
        "撰写",
    ]
    scores = {"code": 0, "research": 0, "analysis": 0, "writing": 0}
    for kw in code_kw:
        if kw in tl:
            scores["code"] += 1
    for kw in research_kw:
        if kw in tl:
            scores["research"] += 1
    for kw in analysis_kw:
        if kw in tl:
            scores["analysis"] += 1
    for kw in writing_kw:
        if kw in tl:
            scores["writing"] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


# ---------------------------------------------------------------------------
# Rule-based lesson extraction
# ---------------------------------------------------------------------------


def rule_extract_lesson(
    agent_name: str,
    iterations: int,
    max_iterations: int,
    task: str,
    result: str,
    task_category: str = "general",
) -> dict | None:
    if iterations >= max_iterations * 0.8 and result:
        return {
            "category": "failed_approach",
            "key": f"lesson:{agent_name}:rule:high_iterations:{int(time.time())}",
            "content": (
                f"Exhausted {iterations}/{max_iterations} iterations on: {task[:100]}. "
                "Next time: decompose complex tasks, narrow scope, or use fewer tools per iteration."
            ),
            "importance": 0.5,
            "source": "rule",
            "task_category": task_category,
            "memory_type": "agent_lesson",
        }
    return None


# ---------------------------------------------------------------------------
# LLM-based lesson extraction (technical)
# ---------------------------------------------------------------------------


async def llm_reflect_lesson(
    agent_name: str,
    task: str,
    result: str,
    task_category: str,
    stats: dict,
    model: str,
    provider_name: str | None = None,
    error_msg: str = "",
) -> dict | None:
    try:
        if error_msg:
            result_text = f"(TASK FAILED) Error: {error_msg[:600]}"
        else:
            result_text = result[:800] if result else "(no output)"

        prompt = (
            f"Based on this completed task, extract ONE concrete lesson.\n\n"
            f"Agent: {agent_name}\n"
            f"Task: {task[:400]}\n"
            f"Output: {result_text}\n"
            f"Stats: {stats['iterations']} steps, {stats['tokens']} tokens, {stats['elapsed']}s\n\n"
            "Identify one specific tip, pitfall, or technique that would help in future similar tasks. "
            "Be specific and actionable. Do not give generic praise.\n\n"
            f"Category (pick one): {task_category}\n\n"
            "If there is truly nothing worth noting, respond with just the word: NONE\n"
            "Otherwise respond with:\n"
            "Category: {category}\n"
            "Insight: {one sentence of actionable advice}"
        )

        llm_params = await _resolve_llm_params(provider_name)
        if not llm_params:
            return None

        response = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.3,
            **llm_params,
        )

        text = _extract_response_text(response)
        if text.strip().upper() in ("NONE", "SKIP"):
            return None

        category = task_category
        insight = ""
        for line in text.split("\n"):
            line = line.strip()
            if line.lower().startswith("category:") or line.startswith("类别:"):
                cat = line.split(":", 1)[1].strip().lower()
                if cat in {"code", "research", "analysis", "writing", "general"}:
                    category = cat
            elif line.lower().startswith("insight:") or line.startswith("经验:") or line.startswith("反思:"):
                insight = line.split(":", 1)[1].strip()

        if not insight:
            insight = text[:250]

        if _is_generic_praise(insight):
            logger.debug("llm_reflect_lesson for %s: insight too generic, skipping", agent_name)
            return None

        if len(insight) < 10:
            logger.warning("llm_reflect_lesson for %s: insight too short (%d chars)", agent_name, len(insight))
            return None

        return {
            "category": "failed_approach" if error_msg else "effective_strategy",
            "key": f"lesson:{agent_name}:llm:{int(time.time())}",
            "content": insight,
            "importance": 0.8 if error_msg else 0.7,
            "source": "llm",
            "task_category": category,
            "memory_type": "agent_lesson",
        }
    except Exception:
        logger.warning("LLM reflection failed for %s", agent_name, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# NEW: LLM-based user preference extraction (Lobehub-style)
# ---------------------------------------------------------------------------


_PREF_BAD_PHRASES = [
    "no preferences",
    "none",
    "nothing notable",
    "no clear preference",
    "无明显偏好",
    "无",
]


async def llm_extract_user_preferences(
    conversation_text: str,
    model: str,
    provider_name: str | None = None,
    max_prefs: int = 3,
) -> list[dict]:
    """Extract user preferences / behavioural rules from a conversation.

    Returns up to ``max_prefs`` structured preferences, each shaped like::

        {
            "key": "user_pref:language",
            "content": "User prefers Chinese for chat, English for code.",
            "category": "language",          # free-form tag
            "importance": 0.7,
            "source": "llm",
            "memory_type": "user_preference",
        }
    """

    if len(conversation_text) < 80:
        return []

    try:
        prompt = (
            "Analyse the following conversation and extract up to "
            f"{max_prefs} concrete preferences or behavioural rules the USER has demonstrated.\n\n"
            "Examples of preferences:\n"
            "- prefers a specific language (Chinese / English)\n"
            "- prefers terse answers vs. detailed explanations\n"
            "- dislikes a library / tool / framework\n"
            "- prefers specific code style (tabs vs spaces, single vs double quotes)\n"
            "- prefers to be addressed in a certain way\n"
            "- explicitly rejected a suggestion (state what and why)\n"
            "- repeatedly asked for a specific format (JSON / markdown table / etc.)\n\n"
            "Rules:\n"
            "- Each preference must be DIRECTLY observable from the conversation.\n"
            "- Be specific and actionable. Avoid vague statements like 'user is friendly'.\n"
            "- If no preference is clearly observable, respond with just: NONE\n\n"
            "Conversation:\n"
            f"{conversation_text[:4000]}\n\n"
            "Respond in this exact format (one preference per block):\n"
            "Category: <one-word tag>\n"
            "Preference: <one sentence, actionable>\n"
            "\n"
            "(repeat for each preference, separated by a blank line)"
        )

        llm_params = await _resolve_llm_params(provider_name)
        if not llm_params:
            return []

        response = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
            temperature=0.2,
            **llm_params,
        )

        text = _extract_response_text(response)
        if not text or text.strip().upper() in ("NONE", "SKIP"):
            return []

        prefs: list[dict] = []
        blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
        for block in blocks:
            cat = "general"
            pref = ""
            for line in block.splitlines():
                line = line.strip()
                if line.lower().startswith("category:") or line.startswith("类别:"):
                    cat = line.split(":", 1)[1].strip().lower() or "general"
                elif line.lower().startswith("preference:") or line.startswith("偏好:"):
                    pref = line.split(":", 1)[1].strip()
            if not pref:
                continue
            if any(bad in pref.lower() for bad in _PREF_BAD_PHRASES):
                continue
            if len(pref) < 8:
                continue
            prefs.append(
                {
                    "key": f"user_pref:{cat}:{int(time.time() * 1000) % 1_000_000}",
                    "content": pref[:500],
                    "category": cat[:50],
                    "importance": 0.7,
                    "source": "llm",
                    "memory_type": "user_preference",
                }
            )
            if len(prefs) >= max_prefs:
                break
        return prefs
    except Exception:
        logger.warning("User-preference extraction failed", exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


async def persist_lesson(
    user_id: int,
    agent_name: str,
    lesson: dict,
    source_session: str = "",
) -> bool:
    if not user_id or not lesson:
        return False
    from crabagent.core.database import agent_memory_upsert

    await agent_memory_upsert(
        user_id=user_id,
        memory_type=lesson.get("memory_type", "agent_lesson"),
        agent_name=agent_name,
        category=lesson.get("category", "effective_strategy"),
        key=lesson["key"],
        content=lesson["content"],
        importance=float(lesson.get("importance", 0.5)),
        confidence=float(lesson.get("confidence", 1.0)),
        source_session=source_session,
        source=lesson.get("source", ""),
        task_category=lesson.get("task_category", ""),
    )
    return True


async def persist_preferences(
    user_id: int,
    preferences: list[dict],
    source_session: str = "",
) -> int:
    if not user_id or not preferences:
        return 0
    from crabagent.core.database import agent_memory_upsert

    saved = 0
    for pref in preferences:
        try:
            await agent_memory_upsert(
                user_id=user_id,
                memory_type=pref.get("memory_type", "user_preference"),
                agent_name="",  # preferences are user-scoped, not agent-scoped
                category=pref.get("category", "general"),
                key=pref["key"],
                content=pref["content"],
                importance=float(pref.get("importance", 0.7)),
                confidence=float(pref.get("confidence", 1.0)),
                source_session=source_session,
                source=pref.get("source", "llm"),
                task_category="",
            )
            saved += 1
        except Exception:
            logger.debug("Failed to persist preference %s", pref.get("key"), exc_info=True)
    return saved


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_llm_params(provider_name: str | None) -> dict | None:
    try:
        provider = await get_provider(provider_name) if provider_name else await get_default_provider()
    except Exception:
        provider = None
    if not provider:
        logger.debug("reflection skipped: no provider available")
        return None
    params: dict[str, Any] = {"api_key": provider.api_key}
    if provider.base_url:
        params["api_base"] = provider.base_url
        params["custom_llm_provider"] = "openai"
    return params


def _extract_response_text(response) -> str:
    if not getattr(response, "choices", None):
        return ""
    msg = response.choices[0].message
    text = (getattr(msg, "content", "") or "").strip()
    if text:
        return text
    reasoning = getattr(msg, "reasoning_content", None)
    if reasoning:
        text = reasoning.strip()
        if "<｜end▁of▁thinking｜>" in text:
            text = text.rsplit(" response", 1)[-1].strip()
    return text


_GENERIC_PRAISE = [
    "completed efficiently",
    "completed in",
    "did a good",
    "well done",
    "great job",
    "successfully completed",
    "完成任务",
    "完成得很好",
    "做得很好",
    "顺利完成",
    "completed the task",
]


def _is_generic_praise(insight: str) -> bool:
    tl = insight.lower()
    return any(bw in tl for bw in _GENERIC_PRAISE)


__all__ = [
    "classify_task",
    "rule_extract_lesson",
    "llm_reflect_lesson",
    "llm_extract_user_preferences",
    "persist_lesson",
    "persist_preferences",
]

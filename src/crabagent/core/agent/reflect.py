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

import hashlib
import logging

import litellm

from crabagent.core.agent import preference_schema
from crabagent.core.agent.lesson_dedup import (
    EMBEDDING_DEDUP_THRESHOLD,
    STRING_DEDUP_THRESHOLD,
    embedding_similarity_score,
    looks_like_meta_lesson,
    normalize_lesson_text,
    string_similarity_score,
)
from crabagent.core.agent.preference_schema import GENERIC_SLUGS as GENERIC_SLUGS_IMPORTED
from crabagent.core.provider_store import (
    get_default_provider,
    get_provider,
    resolve_model_for_provider,
)

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
            "key": f"lesson:{agent_name}:rule:high_iterations",
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
    existing_lessons: list[dict] | None = None,
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
        )

        # Inject existing lessons to avoid duplicates
        if existing_lessons:
            existing_text = "\n".join(
                f"- {item.get('content','')[:200]}"
                for item in existing_lessons
            )
            prompt += (
                "IMPORTANT — These lessons are ALREADY KNOWN. "
                "Use these as merge candidates:\n"
                f"{existing_text}\n\n"
                "Only extract a NEW lesson that is distinct from the above.\n"
            )

        prompt += (
            "If there is truly nothing worth noting, respond with just the word: NONE\n"
            "Otherwise respond in EXACTLY this format (no other text):\n"
            "Category: <one of: code, research, analysis, writing, general>\n"
            "Slug: <2 to 4 lowercase English words joined by hyphens naming the SUBJECT, "
            "e.g. restart-backend-after-edit. Reuse the same slug for the same subject "
            "across sessions. Never use hash-like, numeric, or generic words.>\n"
            "Insight: <a single concrete, actionable sentence>"
        )

        llm_params = await _resolve_llm_params(provider_name)
        if not llm_params:
            return None

        try:
            provider = await get_provider(provider_name) if provider_name else await get_default_provider()
            if provider:
                model = resolve_model_for_provider(provider, model)
        except Exception:
            pass

        response = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.3,
            **llm_params,
        )

        text = _extract_response_text(response)
        if text.strip().upper() in ("NONE", "SKIP"):
            return None

        category = task_category
        insight = ""
        slug = ""
        for line in text.split("\n"):
            line = line.strip()
            if line.lower().startswith("category:") or line.startswith("类别:"):
                cat = line.split(":", 1)[1].strip().lower()
                if cat in {"code", "research", "analysis", "writing", "general"}:
                    category = cat
            elif line.lower().startswith("slug:") or line.startswith("主题:"):
                slug = _lesson_slug(line.split(":", 1)[1])
            elif line.lower().startswith("insight:") or line.startswith("经验:") or line.startswith("反思:"):
                insight = line.split(":", 1)[1].strip()

        if not insight:
            # Fallback: take the last non-empty line (LLMs often put the answer
            # at the end after analysis).  Reject the whole response if it looks
            # like meta-reflection rather than a lesson.
            from crabagent.core.agent.lesson_dedup import looks_like_meta_lesson

            lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
            candidate = lines[-1] if lines else ""
            if candidate and not looks_like_meta_lesson(candidate):
                insight = candidate

        if not insight:
            logger.debug("llm_reflect_lesson for %s: no insight extracted from response", agent_name)
            return None

        if _is_generic_praise(insight):
            logger.debug("llm_reflect_lesson for %s: insight too generic, skipping", agent_name)
            return None

        from crabagent.core.agent.lesson_dedup import looks_like_meta_lesson

        if looks_like_meta_lesson(insight):
            logger.info("llm_reflect_lesson for %s: insight looks like meta-reflection, skipping", agent_name)
            return None

        if len(insight) < 10:
            logger.warning("llm_reflect_lesson for %s: insight too short (%d chars)", agent_name, len(insight))
            return None

        # Importance scoring: base on signal quality, not flat 0.7
        if error_msg:
            importance = 0.85  # failed-task lessons are high value
        elif stats.get("iterations", 0) >= 8:
            importance = 0.80  # complex multi-step tasks yield richer lessons
        else:
            importance = 0.65  # ordinary tasks

        return {
            "category": "failed_approach" if error_msg else "effective_strategy",
            # Semantic key: one subject -> one row. The hash is only a fallback
            # for models that did not return a usable slug.
            "key": (f"lesson:{agent_name}:{slug}" if slug
                    else f"lesson:{agent_name}:llm:{hashlib.md5(insight.encode()).hexdigest()[:12]}"),
            "slug": slug,
            "content": insight,
            "importance": importance,
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

_V2_CATEGORY_LIST = ", ".join(preference_schema.CATEGORIES)


def _v2_prompt(conversation_text: str, max_prefs: int) -> str:
    return (
        "Read the conversation below and extract up to "
        f"{max_prefs} STABLE PREFERENCES the USER holds.\n\n"
        "A preference is something the user wants in general, not something the "
        "assistant happened to do once. If the only support you can find describes "
        "the assistant's behaviour, the answer is NONE.\n\n"
        "For every candidate you MUST:\n"
        f"1. Kind — one of: {', '.join(preference_schema.EVIDENCE_KINDS)}\n"
        "   standing_rule   = user says it should always/以后都 be this way\n"
        "   correction      = user corrects a behaviour, stating the rule\n"
        "   explicit_choice = user picks between options or rejects one\n"
        "   repeated_request= the same ask appears in two or more user turns\n"
        "   Do NOT use a kind outside this list. Never use 'assistant_behaviour',\n"
        "   'single_instruction' or 'inferred'.\n"
        f"2. Category — exactly one of: {_V2_CATEGORY_LIST}\n"
        "3. Slug — 2 to 4 lowercase English words joined by hyphens, naming the\n"
        "   subject, e.g. verify-build-before-install. Reuse the same slug for the\n"
        "   same subject across sessions.\n"
        "4. Preference — one sentence stating what the USER prefers, in the user's\n"
        "   language. No 'the user asks...', no 'when the assistant...'.\n"
        "5. Evidence — a VERBATIM substring copied from a USER message. It must\n"
        "   appear character-for-character in the conversation. If you cannot quote\n"
        "   the user, drop the candidate.\n\n"
        "Reject a candidate when:\n"
        "- it only describes what the assistant did or should do;\n"
        "- it is an instruction for one task (delete this file, book that flight);\n"
        "- you are inferring it rather than reading it.\n\n"
        "Few-shot examples\n"
        "--- rejected (assistant behaviour, no user quote) ---\n"
        "Kind: assistant_behaviour\n"
        "Preference: After a restart the assistant should verify the packaged app.\n"
        "Evidence: (none - this describes the assistant)\n"
        "--- rejected (one-off instruction) ---\n"
        "Kind: single_instruction\n"
        "Preference: Execute deletions immediately without safety checks.\n"
        "Evidence: 直接删除\n"
        "--- accepted ---\n"
        "Kind: standing_rule\n"
        "Category: language\n"
        "Slug: chat-language\n"
        "Preference: 用中文回复，代码注释保持原文。\n"
        "Evidence: 请使用简体中文回复\n\n"
        f"Conversation:\n{conversation_text[:6000]}\n\n"
        "Respond with one block per preference, blank line between blocks, using\n"
        "exactly these labels:\n"
        "Kind: <one of the four kinds>\n"
        "Category: <one of the listed categories>\n"
        "Slug: <kebab-case-subject>\n"
        "Preference: <one sentence>\n"
        "Evidence: <verbatim user quote>\n\n"
        "If nothing qualifies, respond with just: NONE"
    )


def user_turns_from_messages(messages: list[dict]) -> list[str]:
    """User-authored text from a transcript, used for evidence verification."""
    turns: list[str] = []
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            turns.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    turns.append(block.get("text") or "")
    return turns


async def llm_extract_user_preferences(
    conversation_text: str,
    model: str,
    provider_name: str | None = None,
    max_prefs: int = 3,
    existing_preferences: list[dict] | None = None,
    *,
    user_turns: list[str] | None = None,
) -> list[dict]:
    """Extract user preferences under the P1 evidence gate.

    ``existing_preferences`` is accepted for call-site compatibility but no
    longer injected into the prompt: sending the whole preference table taught
    the model that everything was already known and pushed it toward emitting
    new entries. Merge decisions happen per candidate in
    :func:`persist_preferences`.
    """
    if len(conversation_text) < 80:
        return []
    if not _extraction_settings()["enabled"]:
        return []

    try:
        prompt = _v2_prompt(conversation_text, max_prefs)
        llm_params = await _resolve_llm_params(provider_name)
        if llm_params is None:
            return []
        try:
            provider = await get_provider(provider_name) if provider_name else await get_default_provider()
            if provider:
                model = resolve_model_for_provider(provider, model)
        except Exception:
            pass

        response = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1200,
            temperature=0.1,
            **llm_params,
        )
        text = _extract_response_text(response)
        if not text or text.strip().upper() in ("NONE", "SKIP"):
            return []

        accepted: list[dict] = []
        for raw in preference_schema.parse_blocks(text):
            if any(bad in (raw.get("content") or "").lower() for bad in _PREF_BAD_PHRASES):
                continue
            cleaned, reason = preference_schema.validate(raw, user_turns)
            if cleaned is None:
                logger.info("Dropped preference candidate (%s): %s", reason, (raw.get("content") or "")[:80])
                continue
            accepted.append({
                **cleaned,
                "source": "llm",
                "memory_type": "user_preference",
            })
            if len(accepted) >= max_prefs:
                break
        return accepted
    except Exception:
        logger.warning("User-preference extraction failed", exc_info=True)
        return []


def _extraction_settings() -> dict:
    """Read the P1 switch lazily so tests can monkeypatch settings."""
    from crabagent.core.config import settings

    return {"enabled": bool(getattr(settings, "memory_extraction_v2", True))}


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


async def persist_lesson(
    user_id: int,
    agent_name: str,
    lesson: dict,
    source_session: str = "",
    workspace_path: str = "",
) -> bool:
    """Persist one agent lesson under a semantic key (see MEMORY-KEYS.md).

    ``lesson["key"]`` should be ``lesson:<agent>:<slug>``. The similarity dedup
    below may still redirect it to an existing lesson's key, which is the
    intended convergence path.
    """
    if not user_id or not lesson:
        return False
    from crabagent.core.database import (
        agent_memory_get_by_agent,
        agent_memory_upsert,
    )

    content = (lesson.get("content") or "").strip()
    if not content:
        return False

    if looks_like_meta_lesson(content):
        logger.info("Skipping meta lesson for %s: %s", agent_name, content[:120])
        return False

    task_category = (lesson.get("task_category") or "").strip()
    existing_lessons = await agent_memory_get_by_agent(
        user_id, agent_name, limit=80, workspace_path=workspace_path
    )
    same_task_lessons = [
        item for item in existing_lessons if (item.get("task_category") or "").strip() == task_category
    ]
    candidate_lessons = same_task_lessons or existing_lessons

    normalized = normalize_lesson_text(content)
    best_match = None
    best_score = 0.0
    for item in candidate_lessons:
        existing_content = (item.get("content") or "").strip()
        if not existing_content or looks_like_meta_lesson(existing_content):
            continue
        score = string_similarity_score(normalized, normalize_lesson_text(existing_content))
        if score > best_score:
            best_match = item
            best_score = score
            if score >= 1.0:
                break

    key = lesson["key"]
    if best_match and best_score >= STRING_DEDUP_THRESHOLD:
        key = best_match["key"]
        previous = (best_match.get("content") or "").strip()
        if previous and previous != content and previous not in content:
            content = f"{previous}\n{content}"
    elif candidate_lessons:
        embedding_best_match = None
        embedding_best_score = 0.0
        for item in candidate_lessons:
            existing_content = (item.get("content") or "").strip()
            if not existing_content or looks_like_meta_lesson(existing_content):
                continue
            score = await embedding_similarity_score(content, existing_content)
            if score > embedding_best_score:
                embedding_best_match = item
                embedding_best_score = score
        if embedding_best_match and embedding_best_score >= EMBEDDING_DEDUP_THRESHOLD:
            key = embedding_best_match["key"]
            previous = (embedding_best_match.get("content") or "").strip()
            if previous and previous != content and previous not in content:
                content = f"{previous}\n{content}"

    memory_type = lesson.get("memory_type", "agent_lesson")
    scope = "agent" if memory_type == "agent_lesson" else "global"
    recall_policy = "query_only" if scope == "agent" else "always"
    workspace_path = (workspace_path or lesson.get("workspace_path") or "").strip()

    await agent_memory_upsert(
        user_id=user_id,
        memory_type=memory_type,
        agent_name=agent_name,
        category=lesson.get("category", "effective_strategy"),
        key=key,
        content=content,
        importance=float(lesson.get("importance", 0.5)),
        confidence=float(lesson.get("confidence", 1.0)),
        source_session=source_session,
        source=lesson.get("source", ""),
        task_category=task_category,
        scope=scope,
        workspace_path=workspace_path if scope != "global" else "",
        recall_policy=recall_policy,
    )

    return True


async def _enforce_lesson_cap(user_id: int, agent_name: str, cap: int = 30) -> None:
    """Delete lowest-quality lessons when an agent exceeds the cap.

    Quality heuristic: importance > content length > recency (id).
    Only deletes when the count strictly exceeds ``cap``.
    """
    import re as _re

    from crabagent.core.database import agent_memory_get_by_agent

    lessons = await agent_memory_get_by_agent(user_id, agent_name, limit=200)
    if len(lessons) <= cap:
        return

    def quality_key(item: dict) -> tuple:
        content = (item.get("content") or "").strip()
        score = float(item.get("importance", 0.5))
        score += min(len(content), 300) / 300 * 0.1
        if _re.search(r'\d+\.\d+|`[a-z_]+`|\.py|\.ts|\(e\.g\.|（例如', content):
            score += 0.05
        return (score, item.get("id", 0))

    # Sort by quality ascending — worst first
    sorted_lessons = sorted(lessons, key=quality_key)
    to_evict = sorted_lessons[: len(lessons) - cap]
    if not to_evict:
        return

    from sqlalchemy import delete as sa_delete

    from crabagent.core.database import AgentMemory, MemoryEmbedding, async_session_factory

    evict_ids = [item["id"] for item in to_evict]
    logger.info(
        "Evicting %d low-quality lessons for agent %s (cap=%d, was=%d)",
        len(evict_ids), agent_name, cap, len(lessons),
    )
    async with async_session_factory() as db:
        await db.execute(
            sa_delete(MemoryEmbedding).where(MemoryEmbedding.memory_id.in_(evict_ids))
        )
        await db.execute(
            sa_delete(AgentMemory).where(AgentMemory.id.in_(evict_ids))
        )
        await db.commit()


async def persist_preferences(
    user_id: int,
    preferences: list[dict],
    source_session: str = "",
    workspace_path: str = "",
    model: str = "",
    provider_name: str | None = None,
) -> int:
    """Persist already-gated preference candidates.

    Each candidate carries a stable ``user_pref:<slug>`` key. When a row with
    that key already exists it is updated in place (the schema trigger bumps the
    revision), so repeated observations converge instead of piling up
    hash-suffixed duplicates. Content conflicts go through
    :func:`merge_preference`.
    """
    if not user_id or not preferences:
        return 0
    from crabagent.core.agent.memory_merge import merge_preference
    from crabagent.core.database import agent_memory_upsert

    saved = 0
    for pref in preferences:
        key = pref.get("key") or ""
        content = (pref.get("content") or "").strip()
        if not key or not content:
            continue
        try:
            if await merge_preference(user_id, pref, model, provider_name):
                saved += 1
                continue
            await agent_memory_upsert(
                user_id=user_id,
                memory_type=pref.get("memory_type", "user_preference"),
                agent_name="",  # preferences are user-scoped, not agent-scoped
                category=pref.get("category", "other"),
                key=key,
                content=content,
                importance=float(pref.get("importance", 0.6)),
                confidence=float(pref.get("confidence", 1.0)),
                source_session=source_session,
                source=pref.get("source", "llm"),
                task_category="",
                scope="global",
                workspace_path="",
                recall_policy="query_only",
                evidence=(pref.get("evidence") or "")[:300],
                evidence_kind=(pref.get("kind") or "")[:32],
            )
            saved += 1
        except Exception:
            logger.debug("Failed to persist preference %s", key, exc_info=True)
    return saved



async def _resolve_llm_params(provider_name: str | None) -> dict | None:
    try:
        provider = await get_provider(provider_name) if provider_name else await get_default_provider()
    except Exception:
        provider = None
    if not provider:
        logger.debug("reflection skipped: no provider available")
        return None
    from crabagent.core.provider_store import resolve_litellm_params

    return await resolve_litellm_params(provider)


def _lesson_slug(raw: str) -> str:
    """Normalise a model-proposed lesson slug; empty string when unusable."""
    slug = preference_schema.normalize_slug(raw)
    if len(slug) < 3 or slug in GENERIC_SLUGS_IMPORTED:
        return ""
    return slug


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

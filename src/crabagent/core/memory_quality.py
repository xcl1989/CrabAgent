"""Read-only quality scan for automatically extracted memories.

Produces the evidence a human needs to triage legacy rows. It never mutates
anything; deletion stays a user decision made in the Memory page.

Detected issues
---------------
``assistant_behaviour``
    A "preference" that describes what the assistant did or should do rather
    than something the user demonstrated. Heuristic on the content prefix.
``random_key``
    Key carries a hash suffix, i.e. the extractor minted a new key instead of
    refining an existing one. Paired with the nearest same-type neighbour so
    the user can see whether it is a duplicate.
``lesson_overflow``
    An agent holds more than ``LESSON_CAP`` lessons; the stale tail is listed.
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select

from crabagent.core.agent.lesson_dedup import string_similarity_score
from crabagent.core.database import AgentMemory, async_session_factory

LESSON_CAP = 40
NEIGHBOUR_SIMILARITY = 0.55
DUPLICATE_SIMILARITY = 0.85
MAX_ROWS_PER_TYPE = 2000
MAX_PAIRWISE = 600  # per-bucket guard: larger buckets keep only flagged keys
CONTAINMENT_MIN_BYTES = 40

# Row shapes that need a human look. Two distinct patterns:
#   assistant_behaviour — describes the assistant's conduct, not the user.
#   conditional_rule    — "When X happens, do Y": a stable habit or a one-off
#                         instruction; the report cannot tell, the user can.
_ASSISTANT_PREFIX = re.compile(
    r"^(when\s+(the\s+)?(assistant|ai|agent|model)\b"
    r"|the\s+(assistant|ai|agent|model)\s+(should|must|is\s+expected|will|needs?\s+to)\b"
    r"|(助手|模型|ai)(应|需要|会|必须))",
    re.IGNORECASE,
)
_CONDITIONAL_PREFIX = re.compile(
    r"^(when\s+(the\s+)?user\b|when\s+(a|an|the|asking|preparing|running|working|using|testing)\b|if\s+the\s+user\b)",
    re.IGNORECASE,
)
_RANDOM_SUFFIX = re.compile(r":[0-9a-f]{8,}$")


def classify_preference(content: str) -> str | None:
    """Return the issue kind for a preference row, or ``None`` when it reads
    as a genuine user preference."""
    text = (content or "").strip()
    if not text:
        return None
    if _ASSISTANT_PREFIX.match(text):
        return "assistant_behaviour"
    if _CONDITIONAL_PREFIX.match(text):
        return "conditional_rule"
    return None


def has_random_suffix(key: str) -> bool:
    return bool(_RANDOM_SUFFIX.search(key or ""))


_WORD = re.compile(r"[a-z0-9]{3,}|[\u4e00-\u9fff]{2}")
JACCARD_PREFILTER = 0.15


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _nearest(key: str, content: str, pool: list[tuple[str, str]]) -> dict | None:
    """Nearest neighbour by lexical similarity.

    A word-set Jaccard prefilter keeps the O(n·m) ``SequenceMatcher`` for
    plausible pairs only; on the live table this cuts ~32k pairs to a few
    hundred and the whole scan from ~10s to well under a second.
    """
    lowered = content.lower()
    words = _words(lowered)
    lowered_bytes = len(lowered.encode())
    candidates: list[tuple[float, str, str, bool]] = []
    for other_key, other_content in pool:
        if other_key == key:
            continue
        other_lowered = other_content.lower()
        # Byte-based floor: CJK carries ~3 bytes per character, so a character
        # count would silently exclude short Chinese rows from containment.
        contains = (lowered_bytes >= CONTAINMENT_MIN_BYTES
                    and len(other_lowered.encode()) >= CONTAINMENT_MIN_BYTES
                    and (lowered in other_lowered or other_lowered in lowered))
        if contains:
            candidates.append((1.0, other_key, other_lowered, True))
            continue
        other_words = _words(other_lowered)
        if not words or not other_words:
            continue
        jaccard = len(words & other_words) / len(words | other_words)
        if jaccard >= JACCARD_PREFILTER:
            candidates.append((jaccard, other_key, other_lowered, False))
    best, best_score, best_contains = None, 0.0, False
    for _, other_key, other_lowered, contains in candidates:
        score = string_similarity_score(lowered, other_lowered)
        # "same text plus a trailing detail" is the typical extractor duplicate;
        # the substring branch of the similarity helper under-scores it, so
        # treat containment as a duplicate in its own right.
        if score > best_score or (contains and not best_contains):
            best, best_score, best_contains = other_key, score, contains
    if best is None or (best_score < NEIGHBOUR_SIMILARITY and not best_contains):
        return None
    return {"key": best, "similarity": round(best_score, 2),
            "duplicate": best_contains or best_score >= DUPLICATE_SIMILARITY}


async def scan_user_preferences(user_id: int) -> list[dict]:
    async with async_session_factory() as db:
        rows = (await db.execute(
            select(AgentMemory)
            .where(AgentMemory.user_id == user_id, AgentMemory.memory_type == "user_preference")
            .order_by(AgentMemory.updated_at.desc())
            .limit(MAX_ROWS_PER_TYPE)
        )).scalars().all()
    pool = [(r.key, r.content or "") for r in rows]

    findings: list[dict] = []
    for row in rows:
        issues = []
        if classify_preference(row.content):
            issues.append("assistant_behaviour")
        if has_random_suffix(row.key):
            issues.append("random_key")
        if not issues:
            continue
        item = {
            "id": row.id,
            "key": row.key,
            "category": row.category or "",
            "content": row.content or "",
            "importance": row.importance,
            "source_session": row.source_session or "",
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "issues": issues,
        }
        if "random_key" in issues:
            item["nearest"] = _nearest(row.key, row.content or "", pool)
        findings.append(item)
    findings.sort(key=lambda f: (-len(f["issues"]), -max(
        (f.get("nearest") or {}).get("similarity", 0.0), f["importance"] or 0.0)))
    return findings


async def scan_lessons(user_id: int) -> list[dict]:
    async with async_session_factory() as db:
        rows = (await db.execute(
            select(AgentMemory)
            .where(AgentMemory.user_id == user_id, AgentMemory.memory_type == "agent_lesson")
            .order_by(AgentMemory.agent_name, AgentMemory.importance.desc())
            .limit(MAX_ROWS_PER_TYPE)
        )).scalars().all()
    by_agent: dict[str, list[AgentMemory]] = defaultdict(list)
    for row in rows:
        by_agent[row.agent_name or ""].append(row)
    overflow = []
    for agent, items in by_agent.items():
        if len(items) <= LESSON_CAP:
            continue
        for row in items[LESSON_CAP:]:
            overflow.append({
                "id": row.id, "key": row.key, "agent_name": agent, "category": row.category or "",
                "content": row.content or "", "importance": row.importance,
                "access_count": row.access_count or 0,
                "created_at": row.created_at.isoformat() if row.created_at else "",
                "issues": ["lesson_overflow"],
            })
    return overflow


async def build_report(user_id: int) -> dict:
    preferences, lessons = await asyncio.gather(scan_user_preferences(user_id), scan_lessons(user_id))
    duplicates = [f for f in preferences if (f.get("nearest") or {}).get("duplicate")]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "preferences_flagged": len(preferences),
            "assistant_behaviour": sum("assistant_behaviour" in f["issues"] for f in preferences),
            "conditional_rule": sum("conditional_rule" in f["issues"] for f in preferences),
            "random_key": sum("random_key" in f["issues"] for f in preferences),
            "likely_duplicates": len(duplicates),
            "lesson_overflow": len(lessons),
        },
        "preferences": preferences,
        "lessons": lessons,
    }

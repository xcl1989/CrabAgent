from __future__ import annotations

import re
from difflib import SequenceMatcher

from crabagent.core.memory_embed import cosine_similarity, encode_query

STRING_DEDUP_THRESHOLD = 0.85
EMBEDDING_DEDUP_THRESHOLD = 0.92

_META_LESSON_PATTERNS = [
    re.compile(r'^\{one sentence of actionable advice\}\"?$', re.IGNORECASE),
    re.compile(
        r'^(we are given:|we are asked to extract one concrete lesson|the user wants to extract one concrete lesson)',
        re.IGNORECASE,
    ),
    re.compile(r'^我们需要?从提供的.?completed task.?中提取', re.IGNORECASE),
    re.compile(r'^我们需要?(分析|提取).*(教训|lesson)', re.IGNORECASE),
    re.compile(r'^(thinking\.|we need to extract one concrete lesson)', re.IGNORECASE),
    re.compile(r'^1\.\s+\*\*analyze the request:\*\*', re.IGNORECASE),
]


def normalize_lesson_text(text: str) -> str:
    """Normalize lesson text before duplicate comparison."""
    return " ".join((text or "").lower().split())



def looks_like_meta_lesson(text: str) -> bool:
    """Detect analysis traces and placeholders that should never be persisted."""
    content = (text or "").strip()
    if not content:
        return True
    return any(pattern.search(content) for pattern in _META_LESSON_PATTERNS)



def string_similarity_score(left: str, right: str) -> float:
    """Fast lexical similarity used before the more expensive embedding check."""
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return min(len(left), len(right)) / max(len(left), len(right))
    return SequenceMatcher(None, left, right).ratio()


async def embedding_similarity_score(left: str, right: str) -> float:
    """Semantic similarity fallback when lexical matching is inconclusive."""
    left_vec = await encode_query(left)
    if left_vec is None:
        return 0.0
    right_vec = await encode_query(right)
    if right_vec is None:
        return 0.0
    return cosine_similarity(left_vec, right_vec)

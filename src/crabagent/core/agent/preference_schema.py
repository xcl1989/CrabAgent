"""Closed vocabulary for automatically extracted user preferences (P1).

Free-form categories were the root cause of the duplicate explosion: the
extractor invented ~200 one-off tags, ``merge_preference`` bailed out on
``general``, and every candidate minted a fresh ``user_pref:<tag>:<md5>`` key.
This module replaces that with a fixed vocabulary plus an evidence gate, so a
candidate either fits a known bucket with a quotable user statement or is not
written at all.
"""

from __future__ import annotations

import re

# Closed set. The extractor must pick one; anything else is rejected.
CATEGORIES = (
    "language",
    "response_style",
    "code_style",
    "tooling",
    "workflow",
    "delivery_format",
    "safety",
    "collaboration",
    "memory",
    "cost",
    "testing",
    "other",
)

# Accepted evidence, with the importance each one earns. Importance is derived
# rather than model-chosen: the model has no basis for estimating it.
EVIDENCE_KINDS = {
    "standing_rule": 0.8,   # "以后都…" / "from now on" / "always"
    "correction": 0.7,      # user corrects the assistant's behaviour
    "explicit_choice": 0.6,  # user picks between options or rejects one
    "repeated_request": 0.6,  # same ask appears in >=2 user turns
}

# Rejected shapes. Kept as named constants so logs and tests can refer to them.
REJECTED_KINDS = ("assistant_behaviour", "single_instruction", "inferred")

MIN_EVIDENCE_BYTES = 3
MAX_EVIDENCE_CHARS = 300
MIN_CONTENT_BYTES = 12  # ~4 Chinese characters; character counts penalise CJK
MAX_CONTENT_CHARS = 500
MIN_SLUG_CHARS = 3
MAX_SLUG_CHARS = 48

# A slug must identify a subject; these do not.
GENERIC_SLUGS = frozenset({
    "general", "misc", "other", "none", "null", "miscellaneous", "various",
    "preference", "preferences", "user", "userpref", "note", "notes", "tmp",
})

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def derive_importance(kind: str) -> float:
    return EVIDENCE_KINDS.get(kind, 0.6)


def normalize_slug(raw: str) -> str:
    """Reduce a model-proposed subject to a stable kebab-case slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", (raw or "").strip().lower()).strip("-")
    if len(slug) > MAX_SLUG_CHARS:
        slug = slug[:MAX_SLUG_CHARS].rstrip("-")
    return slug


def build_key(slug: str) -> str:
    """The key is the slug alone.

    Category is deliberately excluded: it is model-assigned metadata that can be
    revised, and including it fragmented one subject across rows whenever the
    model picked a different tag (see MEMORY-KEYS.md).
    """
    return f"user_pref:{slug}"


def validate(candidate: dict, user_turns: list[str] | None = None) -> tuple[dict | None, str]:
    """Return ``(cleaned, reason)``; ``cleaned`` is None when rejected.

    ``reason`` is a short machine-friendly tag used in logs and tests.
    """
    if not isinstance(candidate, dict):
        return None, "not_a_dict"

    content = (candidate.get("content") or "").strip()
    if len(content.encode()) < MIN_CONTENT_BYTES:
        return None, "content_too_short"
    if len(content) > MAX_CONTENT_CHARS:
        content = content[:MAX_CONTENT_CHARS]

    kind = (candidate.get("kind") or "").strip().lower()
    if kind in REJECTED_KINDS:
        return None, f"rejected_kind:{kind}"
    if kind not in EVIDENCE_KINDS:
        return None, "unknown_kind"

    evidence = (candidate.get("evidence") or "").strip()
    if len(evidence.encode()) < MIN_EVIDENCE_BYTES:
        return None, "no_evidence"
    if len(evidence) > MAX_EVIDENCE_CHARS:
        evidence = evidence[:MAX_EVIDENCE_CHARS]

    # The quote must actually occur in what the user said. This is what stops
    # "the assistant did X" from being recorded as a user preference.
    if user_turns is not None:
        haystack = "\n".join(user_turns).casefold()
        if evidence.casefold() not in haystack:
            return None, "evidence_not_verbatim"

    category = (candidate.get("category") or "").strip().lower()
    if category not in CATEGORIES:
        return None, f"unknown_category:{category or '<empty>'}"

    slug = normalize_slug(candidate.get("slug") or "")
    if len(slug) < MIN_SLUG_CHARS or not _SLUG_RE.match(slug):
        return None, f"bad_slug:{slug or '<empty>'}"
    if slug in GENERIC_SLUGS:
        return None, f"generic_slug:{slug}"

    return {
        "key": build_key(slug),
        "content": content,
        "category": category,
        "slug": slug,
        "kind": kind,
        "evidence": evidence,
        "importance": derive_importance(kind),
    }, "ok"


def parse_blocks(text: str) -> list[dict]:
    """Parse the extractor's block format into raw candidate dicts.

    Accepted line labels (English or Chinese):
        Kind / 类型, Category / 类别, Slug / 主题, Preference / 偏好, Evidence / 依据
    """
    fields = {
        "kind": ("kind", "类型"),
        "category": ("category", "类别"),
        "slug": ("slug", "主题"),
        "content": ("preference", "偏好"),
        "evidence": ("evidence", "依据", "quote", "原文"),
    }
    candidates: list[dict] = []
    for block in (b.strip() for b in text.split("\n\n")):
        if not block:
            continue
        item: dict[str, str] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            label, value = line.split(":", 1)
            label = label.strip().lower()
            for name, aliases in fields.items():
                if label in aliases:
                    item[name] = value.strip()
                    break
        if "content" in item:
            candidates.append(item)
    return candidates

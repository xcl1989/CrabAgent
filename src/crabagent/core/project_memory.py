"""Project Memory — workspace-level context from existing data.

Aggregates lessons, tech stack, and activity info for a workspace
using **zero** additional LLM calls. All data comes from:
- ``agent_memory`` → filtered by workspace via ``source_session`` JOIN
- Project file heuristics (``pyproject.toml``, ``package.json``, …)
- ``conversations`` table timestamps

Usage::

    pm = await ProjectMemory.load(user_id, workspace)
    if pm:
        prompt += pm.to_prompt()
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tech-stack detection helpers
# ---------------------------------------------------------------------------

_TECH_STACK_RULES: list[tuple[str, list[str], str]] = [
    # (display_name, indicator_files, extra)
    ("Python", ["pyproject.toml", "setup.py", "requirements.txt"], ""),
    ("FastAPI", ["pyproject.toml"], "fastapi"),
    ("Django", ["manage.py", "django"], ""),
    ("SQLAlchemy", ["pyproject.toml", "requirements.txt"], "sqlalchemy"),
    ("Node.js", ["package.json"], ""),
    ("React", ["package.json"], "react"),
    ("Vue", ["package.json"], "vue"),
    ("TypeScript", ["tsconfig.json", "package.json"], "typescript"),
    ("Rust", ["Cargo.toml"], ""),
    ("Go", ["go.mod"], ""),
    ("Ruby", ["Gemfile"], ""),
    ("Docker", ["Dockerfile", "docker-compose.yml"], ""),
]

_CACHE_TTL = 3600  # seconds


def _detect_tech_stack(workspace: Path) -> list[str]:
    """Scan *workspace* for indicator files and return a sorted list of tags."""
    stack: list[str] = []
    file_cache: dict[str, bool] = {}

    def _has(fname: str) -> bool:
        if fname not in file_cache:
            file_cache[fname] = (workspace / fname).is_file()
        return file_cache[fname]

    def _file_contains(fname: str, keyword: str) -> bool:
        path = workspace / fname
        if not path.is_file():
            return False
        try:
            return keyword in path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return False

    for display_name, indicators, extra in _TECH_STACK_RULES:
        if any(_has(f) for f in indicators):
            if extra and not _file_contains(indicators[0], extra):
                continue
            stack.append(display_name)

    # Fallback: empty or unknown
    return stack if stack else ["(unknown)"]


def _load_cached_stack(workspace: Path) -> list[str] | None:
    """Read cached tech stack from ``.crabagent/tech-stack.json``."""
    cache_file = workspace / ".crabagent" / "tech-stack.json"
    if not cache_file.is_file():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        if data.get("timestamp", 0) + _CACHE_TTL > time.time():
            return data.get("stack", [])
    except Exception:
        pass
    return None


def _save_cached_stack(workspace: Path, stack: list[str]) -> None:
    cache_file = workspace / ".crabagent" / "tech-stack.json"
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps({"stack": stack, "timestamp": time.time()}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def get_tech_stack(workspace: Path) -> list[str]:
    """Return detected tech stack (cached for ``_CACHE_TTL`` seconds)."""
    cached = _load_cached_stack(workspace)
    if cached is not None:
        return cached
    stack = _detect_tech_stack(workspace)
    _save_cached_stack(workspace, stack)
    return stack


# ---------------------------------------------------------------------------
# ProjectProfile
# ---------------------------------------------------------------------------


@dataclass
class ProjectProfile:
    workspace: str
    tech_stack: list[str] = field(default_factory=list)
    recent_lessons: list[str] = field(default_factory=list)
    lesson_count: int = 0
    last_active: str = ""

    def to_prompt(self) -> str:
        """Format as a short context block for injection into system prompts."""
        parts: list[str] = []

        if self.last_active:
            parts.append(f"上次活跃：{self.last_active}")

        if self.tech_stack and self.tech_stack != ["(unknown)"]:
            parts.append(f"技术栈：{' / '.join(self.tech_stack)}")

        if self.recent_lessons:
            lessons = "；".join(self.recent_lessons[:5])
            if self.lesson_count > 5:
                lessons += f" 等{self.lesson_count}条"
            parts.append(f"项目经验：{lessons}")

        if not parts:
            return ""

        return "=== 项目上下文 ===\n" + "\n".join(parts) + "\n====================\n"


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------


async def load_project_memory(
    user_id: int,
    workspace: str | Path,
    lesson_limit: int = 8,
) -> ProjectProfile | None:
    """Build a :class:`ProjectProfile` for *workspace*.

    Returns ``None`` when there is no data at all (no lessons, no tech stack)
    so callers can skip injection cleanly.
    """
    from crabagent.core.database import agent_memory_get_by_workspace

    ws = Path(workspace).resolve()
    ws_str = str(ws)

    ws_lessons = await agent_memory_get_by_workspace(
        user_id=user_id,
        workspace=ws_str,
        limit=lesson_limit,
    )

    if not ws_lessons:
        # Tech-stack only — still useful for new projects
        stack = get_tech_stack(ws)
        if stack == ["(unknown)"]:
            return None
        return ProjectProfile(
            workspace=ws_str,
            tech_stack=stack,
        )

    # Most recent lesson timestamp → last_active
    last_ts = ws_lessons[0].get("created_at")
    last_active = last_ts.strftime("%m-%d %H:%M") if last_ts else ""

    contents = [l["content"] for l in ws_lessons if l.get("content")]
    total = len(contents)

    return ProjectProfile(
        workspace=ws_str,
        tech_stack=get_tech_stack(ws),
        recent_lessons=contents[:5],
        lesson_count=total,
        last_active=last_active,
    )


__all__ = [
    "get_tech_stack",
    "load_project_memory",
    "ProjectProfile",
]

"""Validation for bounded, platform-neutral game input plans.

This module only validates plans; it does not dispatch input events.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MAX_STEPS = 8
MAX_TOTAL_MS = 2000
MAX_HOLD_MS = 1000
MAX_KEYS = 4
GAME_KEYS = frozenset(
    {f"Key{chr(code)}" for code in range(ord("A"), ord("Z") + 1)}
    | {f"Digit{digit}" for digit in range(10)}
    | {"ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Space"}
)


@dataclass(frozen=True)
class GameStep:
    kind: str
    duration_ms: int
    keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class GamePlan:
    steps: tuple[GameStep, ...]
    total_ms: int


def validate_game_plan(steps: Any) -> GamePlan:
    """Reject unknown actions and ambiguous inputs before any event is dispatched."""
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise ValueError(f"steps must contain between 1 and {MAX_STEPS} actions")
    validated: list[GameStep] = []
    total = 0
    for item in steps:
        if not isinstance(item, dict):
            raise ValueError("each step must be an object")
        kind = item.get("type")
        if kind not in ("hold_keys", "wait"):
            raise ValueError("unsupported game action")
        allowed = {"type", "duration_ms", "keys"} if kind == "hold_keys" else {"type", "duration_ms"}
        if set(item) - allowed:
            raise ValueError("unexpected step fields")
        duration = item.get("duration_ms")
        if type(duration) is not int or not 1 <= duration <= MAX_HOLD_MS:
            raise ValueError(f"duration_ms must be an integer between 1 and {MAX_HOLD_MS}")
        keys: tuple[str, ...] = ()
        if kind == "hold_keys":
            raw_keys = item.get("keys")
            if not isinstance(raw_keys, list) or not 1 <= len(raw_keys) <= MAX_KEYS:
                raise ValueError(f"keys must contain between 1 and {MAX_KEYS} keys")
            if any(not isinstance(key, str) or key not in GAME_KEYS for key in raw_keys):
                raise ValueError("unsupported game key")
            if len(set(raw_keys)) != len(raw_keys):
                raise ValueError("duplicate game key")
            keys = tuple(raw_keys)
        total += duration
        if total > MAX_TOTAL_MS:
            raise ValueError(f"plan exceeds {MAX_TOTAL_MS} ms")
        validated.append(GameStep(kind, duration, keys))
    return GamePlan(tuple(validated), total)

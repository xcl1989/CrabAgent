"""Bounded in-memory execution for one Agent computer task."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ComputerSession:
    started: float = field(default_factory=time.monotonic)
    actions: int = 0
    observations: int = 0
    failures: int = 0
    stopped: bool = False

    def check(self, *, observe: bool = False) -> None:
        if self.stopped:
            raise RuntimeError("STOPPED: user stopped computer actions")
        if time.monotonic() - self.started > 15 * 60:
            raise RuntimeError("BUDGET_EXCEEDED: task timed out")
        if self.failures >= 3:
            raise RuntimeError("BUDGET_EXCEEDED: too many consecutive errors")
        if self.actions >= 60 or (observe and self.observations >= 20):
            raise RuntimeError("BUDGET_EXCEEDED: action or observation limit reached")

    def record(self, result: dict[str, Any], *, observe: bool = False) -> None:
        if observe:
            self.observations += 1
        else:
            self.actions += 1
        self.failures = self.failures + 1 if result.get("status") in {"failed", "blocked"} else 0


def get_session(context: Any) -> ComputerSession:
    if context is None:
        raise RuntimeError("Computer actions require an active Agent context")
    return context.metadata.setdefault("_computer_session", ComputerSession())

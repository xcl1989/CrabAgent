"""Bounded in-memory execution for one Agent computer task."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ComputerSession:
    started: float = field(default_factory=lambda: time.monotonic())
    active: float = 0.0
    _tracking: int = field(default=0, init=False, repr=False)
    _active_started: float = field(default=0.0, init=False, repr=False)
    actions: int = 0
    observations: int = 0
    failures: int = 0
    stopped: bool = False

    @property
    def active_seconds(self) -> float:
        return self.active + (time.monotonic() - self._active_started if self._tracking else 0.0)

    @contextmanager
    def track(self) -> Iterator[None]:
        # Count the union of overlapping calls, including failures and cancellation.
        if not self._tracking:
            self._active_started = time.monotonic()
        self._tracking += 1
        try:
            yield
        finally:
            self._tracking -= 1
            if not self._tracking:
                self.active += time.monotonic() - self._active_started

    def check(self, *, observe: bool = False) -> None:
        if self.stopped:
            raise RuntimeError("STOPPED: user stopped computer actions")
        if self.active_seconds >= 15 * 60:
            raise RuntimeError("BUDGET_EXCEEDED: task timed out")
        if time.monotonic() - self.started >= 60 * 60:
            raise RuntimeError("BUDGET_EXCEEDED: task expired")
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

from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    WAITING_USER = "waiting_user"
    DONE = "done"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


OPEN_TASK_STATUSES = (
    TaskStatus.PENDING.value,
    TaskStatus.IN_PROGRESS.value,
    TaskStatus.WAITING_USER.value,
    TaskStatus.PARTIAL.value,
    TaskStatus.FAILED.value,
)
ACTIVE_TASK_STATUSES = (
    TaskStatus.IN_PROGRESS.value,
    TaskStatus.WAITING_USER.value,
)
USER_ACTIONABLE_TASK_STATUSES = (
    TaskStatus.WAITING_USER.value,
    TaskStatus.PARTIAL.value,
    TaskStatus.FAILED.value,
)
CLOSED_TASK_STATUSES = (
    TaskStatus.DONE.value,
    TaskStatus.CANCELLED.value,
)
TASK_STATUS_VALUES = tuple(status.value for status in TaskStatus)


def is_open_task_status(status: str) -> bool:
    return status in OPEN_TASK_STATUSES


def is_closed_task_status(status: str) -> bool:
    return status in CLOSED_TASK_STATUSES


def validate_task_status(status: str) -> str:
    if status not in TASK_STATUS_VALUES:
        allowed = ", ".join(TASK_STATUS_VALUES)
        raise ValueError(f"Invalid task status {status!r}; expected one of: {allowed}")
    return status

from __future__ import annotations

import logging

from crabagent.core.agent.tools.registry import registry

logger = logging.getLogger(__name__)


def _get_locale(context) -> str:
    """Get locale from agent context."""
    if context and context.metadata:
        return context.metadata.get("locale", getattr(context, "locale", "en"))
    return getattr(context, "locale", "en") if context else "en"


def _t(key: str, locale: str = "en", **kwargs) -> str:
    """Get translated message."""
    from crabagent.core.i18n import get_tool_message

    msg = get_tool_message(key, locale)
    return msg.format(**kwargs) if kwargs else msg


async def _get_db():
    from crabagent.core.database import async_session_factory

    return async_session_factory()


async def _tasks_to_str(tasks: list, locale: str = "en", show_all: bool = False) -> str:
    if not tasks:
        return _t("scheduled_task_no_tasks", locale)
    lines = [_t("scheduled_task_list_title", locale)]
    for t in tasks:
        icon = "\u2705" if t.enabled else "\u23f8\ufe0f"
        last = ""
        if t.last_run_at:
            ts = (
                t.last_run_at.strftime("%Y-%m-%d %H:%M")
                if hasattr(t.last_run_at, "strftime")
                else str(t.last_run_at)[:16]
            )
            last = _t("scheduled_task_last_run", locale, time=ts, status=t.last_status or "ok")
        model_info = f" [{t.model}]" if t.model else ""
        lines.append(f"{icon} #{t.id} {t.name} \u2014 `{t.cron_expression}`{model_info}{last}")
        if show_all:
            lines.append(f"{_t('scheduled_task_prompt_label', locale)} {t.prompt[:200]}")
            if t.last_error:
                lines.append(f"{_t('scheduled_task_last_error', locale)} {t.last_error[:200]}")
    return "\n".join(lines)


@registry.register(
    name="scheduled_task_create",
    description=(
        "Create a scheduled task that sends a question to AI at specified cron intervals."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Task name, e.g. 'Daily project status check'.",
            },
            "question": {
                "type": "string",
                "description": "The complete question to send to AI, e.g. 'Query project count and summarize'.",
            },
            "cron_expression": {
                "type": "string",
                "description": (
                    "APScheduler cron expression, 5 fields separated by spaces: "
                    "min(0-59) hour(0-23) day(1-31) month(1-12) weekday(0-6). "
                    "E.g. '0 9 * * *' = daily at 9am, '0 5 1 * *' = 1st of month at 5am, "
                    "'*/30 * * * *' = every 30 min. Must be exactly 5 fields."
                ),
            },
            "model": {
                "type": "string",
                "description": "Optional, specify model ID. Leave empty for default model.",
            },
        },
        "required": ["name", "question", "cron_expression"],
    },
    metadata={"source": "builtin", "category": "scheduled"},
)
async def scheduled_task_create(
    name: str,
    question: str,
    cron_expression: str,
    model: str | None = None,
    context=None,
) -> str:
    from sqlalchemy import select

    from crabagent.core.database import ScheduledTask, User

    locale = _get_locale(context)
    db = await _get_db()
    try:
        user_id = 1
        if context and context.metadata:
            try:
                from crabagent.core.database import async_session_factory as _asf

                async with _asf() as _s:
                    r = await _s.execute(select(User).where(User.username == "admin"))
                    u = r.scalar_one_or_none()
                    if u:
                        user_id = u.id
            except Exception:
                pass

        resolved_model = model or ""
        if not resolved_model and context:
            resolved_model = context.model or context.metadata.get("resolved_model", "") or ""

        parts = cron_expression.strip().split()
        if len(parts) != 5:
            return _t("scheduled_task_cron_error", locale, cron=cron_expression)

        task = ScheduledTask(
            user_id=user_id,
            name=name,
            prompt=question,
            cron_expression=cron_expression.strip(),
            model=resolved_model,
            enabled=True,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

        from crabagent.serve.scheduler import get_scheduler

        await get_scheduler().add_task(task)

        model_str = (
            _t("scheduled_task_model", locale, model=resolved_model)
            if resolved_model
            else _t("scheduled_task_default_model", locale)
        )
        return _t(
            "scheduled_task_created", locale,
            id=task.id, name=name, cron=cron_expression, model=model_str,
        )
    except Exception as e:
        await db.rollback()
        return _t("scheduled_task_create_error", locale, error=str(e))
    finally:
        await db.close()


@registry.register(
    name="scheduled_task_list",
    description=(
        "List all scheduled tasks for the current user, "
        "including enabled status, cron expression, last execution time, etc."
    ),
    parameters={"type": "object", "properties": {}},
    metadata={"source": "builtin", "category": "scheduled"},
)
async def scheduled_task_list(context=None) -> str:
    from sqlalchemy import select

    from crabagent.core.database import ScheduledTask

    locale = _get_locale(context)
    db = await _get_db()
    try:
        result = await db.execute(select(ScheduledTask).order_by(ScheduledTask.created_at.desc()))
        tasks = result.scalars().all()
        return await _tasks_to_str(list(tasks), locale=locale, show_all=True)
    except Exception as e:
        return _t("scheduled_task_list_error", locale, error=str(e))
    finally:
        await db.close()


@registry.register(
    name="scheduled_task_update",
    description=(
        "Update an existing scheduled task's name, question, or execution time. "
        "Only pass the fields you want to change."
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "The task ID to update.",
            },
            "name": {
                "type": "string",
                "description": "New task name.",
            },
            "question": {
                "type": "string",
                "description": "New question content.",
            },
            "cron_expression": {
                "type": "string",
                "description": "New cron expression.",
            },
        },
        "required": ["task_id"],
    },
    metadata={"source": "builtin", "category": "scheduled"},
)
async def scheduled_task_update(
    task_id: int,
    name: str | None = None,
    question: str | None = None,
    cron_expression: str | None = None,
    context=None,
) -> str:
    from sqlalchemy import select

    from crabagent.core.database import ScheduledTask

    locale = _get_locale(context)
    db = await _get_db()
    try:
        result = await db.execute(select(ScheduledTask).where(ScheduledTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return _t("scheduled_task_not_found", locale, id=task_id)

        changes = []
        if name is not None:
            task.name = name
            changes.append(f"name\u2192{name}")
        if question is not None:
            task.prompt = question
            changes.append("prompt updated")
        if cron_expression is not None:
            parts = cron_expression.strip().split()
            if len(parts) != 5:
                return _t("scheduled_task_cron_error", locale, cron=cron_expression)
            from crabagent.serve.scheduler import get_scheduler

            task.cron_expression = cron_expression.strip()
            await get_scheduler().remove_task(task_id)
            await get_scheduler().add_task(task)
            changes.append(f"cron\u2192{cron_expression}")

        await db.commit()

        if not changes:
            return _t("scheduled_task_no_changes", locale, id=task_id)
        return _t("scheduled_task_updated", locale, id=task_id, changes=", ".join(changes))
    except Exception as e:
        await db.rollback()
        return _t("scheduled_task_update_error", locale, error=str(e))
    finally:
        await db.close()


@registry.register(
    name="scheduled_task_delete",
    description="Delete a scheduled task.",
    parameters={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "The task ID to delete.",
            },
        },
        "required": ["task_id"],
    },
    metadata={"source": "builtin", "category": "scheduled"},
)
async def scheduled_task_delete(task_id: int, context=None) -> str:
    from sqlalchemy import delete

    from crabagent.core.database import ScheduledTask
    from crabagent.serve.scheduler import get_scheduler

    locale = _get_locale(context)
    db = await _get_db()
    try:
        await get_scheduler().remove_task(task_id)
        await db.execute(delete(ScheduledTask).where(ScheduledTask.id == task_id))
        await db.commit()
        return _t("scheduled_task_deleted", locale, id=task_id)
    except Exception as e:
        await db.rollback()
        return _t("scheduled_task_delete_error", locale, error=str(e))
    finally:
        await db.close()


@registry.register(
    name="scheduled_task_pause",
    description="Pause a scheduled task. It will not auto-execute but can be resumed at any time.",
    parameters={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "The task ID to pause.",
            },
        },
        "required": ["task_id"],
    },
    metadata={"source": "builtin", "category": "scheduled"},
)
async def scheduled_task_pause(task_id: int, context=None) -> str:
    from sqlalchemy import select

    from crabagent.core.database import ScheduledTask
    from crabagent.serve.scheduler import get_scheduler

    locale = _get_locale(context)
    db = await _get_db()
    try:
        result = await db.execute(select(ScheduledTask).where(ScheduledTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return _t("scheduled_task_not_found", locale, id=task_id)
        task.enabled = False
        await db.commit()
        await get_scheduler().remove_task(task_id)
        return _t("scheduled_task_paused", locale, id=task_id, name=task.name)
    except Exception as e:
        await db.rollback()
        return _t("scheduled_task_pause_error", locale, error=str(e))
    finally:
        await db.close()


@registry.register(
    name="scheduled_task_resume",
    description="Resume a paused scheduled task.",
    parameters={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "The task ID to resume.",
            },
        },
        "required": ["task_id"],
    },
    metadata={"source": "builtin", "category": "scheduled"},
)
async def scheduled_task_resume(task_id: int, context=None) -> str:
    from sqlalchemy import select

    from crabagent.core.database import ScheduledTask
    from crabagent.serve.scheduler import get_scheduler

    locale = _get_locale(context)
    db = await _get_db()
    try:
        result = await db.execute(select(ScheduledTask).where(ScheduledTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return _t("scheduled_task_not_found", locale, id=task_id)
        task.enabled = True
        await db.commit()
        await get_scheduler().add_task(task)
        return _t("scheduled_task_resumed", locale, id=task_id, name=task.name, cron=task.cron_expression)
    except Exception as e:
        await db.rollback()
        return _t("scheduled_task_resume_error", locale, error=str(e))
    finally:
        await db.close()

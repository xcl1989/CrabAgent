from __future__ import annotations

import logging

from crabagent.core.agent.tools.registry import registry

logger = logging.getLogger(__name__)


async def _get_db():
    from crabagent.core.database import async_session_factory

    return async_session_factory()


async def _tasks_to_str(tasks: list, show_all: bool = False) -> str:
    if not tasks:
        return "没有定时任务。"
    lines = ["# 定时任务列表\n"]
    for t in tasks:
        status = "✅" if t.enabled else "⏸️"
        last = ""
        if t.last_run_at:
            ts = (
                t.last_run_at.strftime("%Y-%m-%d %H:%M")
                if hasattr(t.last_run_at, "strftime")
                else str(t.last_run_at)[:16]
            )
            last = f" 上次: {ts} ({t.last_status or 'ok'})"
        model_info = f" [{t.model}]" if t.model else ""
        lines.append(f"{status} #{t.id} {t.name} — `{t.cron_expression}`{model_info}{last}")
        if show_all:
            lines.append(f"   提示词: {t.prompt[:200]}")
            if t.last_error:
                lines.append(f"   上次错误: {t.last_error[:200]}")
    return "\n".join(lines)


@registry.register(
    name="scheduled_task_create",
    description=(
        "创建定时任务。将一个问题按 cron 表达式定时发送给 AI 执行。"
        "参数: name(任务名称), question(要发送给AI的问题), cron_expression(APScheduler标准cron，5段空格分隔：分 时 日 月 周，*表示任意值，如 '0 9 * * *' 表示每天9点，'0 5 16 4 *' 表示4月16日5点，'*/30 * * * *' 表示每30分钟), model(可选，指定模型ID)"
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "任务名称，如'每日在建项目查询'",
            },
            "question": {
                "type": "string",
                "description": "要发送给 AI 的完整问题，如'查询在建项目数量并汇总'",
            },
            "cron_expression": {
                "type": "string",
                "description": "APScheduler cron 表达式，5个字段用空格分隔：分(0-59) 时(0-23) 日(1-31) 月(1-12) 周(0-6)。例如 '0 9 * * *' 每天9点，'0 5 1 * *' 每月1日5点，'0 9 * * 1-5' 工作日9点，'*/30 * * * *' 每30分钟。必须是5个字段，多填或少填都会导致任务无法执行。",
            },
            "model": {
                "type": "string",
                "description": "可选，指定模型ID。不填使用默认模型",
            },
        },
        "required": ["name", "question", "cron_expression"],
    },
    metadata={"source": "builtin", "category": "scheduled"},
)
async def scheduled_task_create(
    name: str, question: str, cron_expression: str,
    model: str | None = None, context=None,
) -> str:
    from sqlalchemy import select

    from crabagent.core.database import ScheduledTask, User

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
            return f"错误：cron 表达式必须包含5个字段（分 时 日 月 周），用空格分隔。当前输入: '{cron_expression}'"

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

        model_str = f" (模型: {resolved_model})" if resolved_model else " (默认模型)"
        return (
            f"定时任务已创建：#{task.id} '{name}' — cron: "
            f"`{cron_expression}`{model_str}。任务已启用，到时间会自动执行。"
        )
    except Exception as e:
        await db.rollback()
        return f"创建定时任务失败：{e}"
    finally:
        await db.close()


@registry.register(
    name="scheduled_task_list",
    description="列出当前用户的所有定时任务，包括启用状态、cron表达式、上次执行时间等",
    parameters={"type": "object", "properties": {}},
    metadata={"source": "builtin", "category": "scheduled"},
)
async def scheduled_task_list(context=None) -> str:
    from sqlalchemy import select

    from crabagent.core.database import ScheduledTask

    db = await _get_db()
    try:
        result = await db.execute(select(ScheduledTask).order_by(ScheduledTask.created_at.desc()))
        tasks = result.scalars().all()
        return await _tasks_to_str(list(tasks), show_all=True)
    except Exception as e:
        return f"获取任务列表失败：{e}"
    finally:
        await db.close()


@registry.register(
    name="scheduled_task_update",
    description="修改已有定时任务的名称、问题或执行时间。只需传入要修改的字段。参数: task_id(任务ID), name(可选), question(可选), cron_expression(可选)",
    parameters={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "要修改的任务ID",
            },
            "name": {
                "type": "string",
                "description": "新的任务名称",
            },
            "question": {
                "type": "string",
                "description": "新的问题内容",
            },
            "cron_expression": {
                "type": "string",
                "description": "新的 cron 表达式",
            },
        },
        "required": ["task_id"],
    },
    metadata={"source": "builtin", "category": "scheduled"},
)
async def scheduled_task_update(
    task_id: int, name: str | None = None,
    question: str | None = None, cron_expression: str | None = None, context=None,
) -> str:
    from sqlalchemy import select

    from crabagent.core.database import ScheduledTask

    db = await _get_db()
    try:
        result = await db.execute(select(ScheduledTask).where(ScheduledTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return f"任务 #{task_id} 不存在"

        changes = []
        if name is not None:
            task.name = name
            changes.append(f"名称→{name}")
        if question is not None:
            task.prompt = question
            changes.append("提示词已更新")
        if cron_expression is not None:
            parts = cron_expression.strip().split()
            if len(parts) != 5:
                return f"错误：cron 表达式必须包含5个字段。当前输入: '{cron_expression}'"
            from crabagent.serve.scheduler import get_scheduler

            task.cron_expression = cron_expression.strip()
            await get_scheduler().remove_task(task_id)
            await get_scheduler().add_task(task)
            changes.append(f"cron→{cron_expression}")

        await db.commit()

        if not changes:
            return f"任务 #{task_id} 未做任何修改"
        return f"任务 #{task_id} 已更新：{', '.join(changes)}"
    except Exception as e:
        await db.rollback()
        return f"修改任务失败：{e}"
    finally:
        await db.close()


@registry.register(
    name="scheduled_task_delete",
    description="删除一个定时任务。参数: task_id(要删除的任务ID)",
    parameters={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "要删除的任务ID",
            },
        },
        "required": ["task_id"],
    },
    metadata={"source": "builtin", "category": "scheduled"},
)
async def scheduled_task_delete(task_id: int) -> str:
    from sqlalchemy import delete

    from crabagent.core.database import ScheduledTask
    from crabagent.serve.scheduler import get_scheduler

    db = await _get_db()
    try:
        await get_scheduler().remove_task(task_id)
        await db.execute(delete(ScheduledTask).where(ScheduledTask.id == task_id))
        await db.commit()
        return f"定时任务 #{task_id} 已删除"
    except Exception as e:
        await db.rollback()
        return f"删除任务失败：{e}"
    finally:
        await db.close()


@registry.register(
    name="scheduled_task_pause",
    description="暂停一个定时任务，暂停后不会自动执行，但可以随时恢复。参数: task_id(任务ID)",
    parameters={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "要暂停的任务ID",
            },
        },
        "required": ["task_id"],
    },
    metadata={"source": "builtin", "category": "scheduled"},
)
async def scheduled_task_pause(task_id: int) -> str:
    from sqlalchemy import select

    from crabagent.core.database import ScheduledTask
    from crabagent.serve.scheduler import get_scheduler

    db = await _get_db()
    try:
        result = await db.execute(select(ScheduledTask).where(ScheduledTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return f"任务 #{task_id} 不存在"
        task.enabled = False
        await db.commit()
        await get_scheduler().remove_task(task_id)
        return f"任务 #{task_id} '{task.name}' 已暂停"
    except Exception as e:
        await db.rollback()
        return f"暂停任务失败：{e}"
    finally:
        await db.close()


@registry.register(
    name="scheduled_task_resume",
    description="恢复一个已暂停的定时任务。参数: task_id(任务ID)",
    parameters={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "要恢复的任务ID",
            },
        },
        "required": ["task_id"],
    },
    metadata={"source": "builtin", "category": "scheduled"},
)
async def scheduled_task_resume(task_id: int) -> str:
    from sqlalchemy import select

    from crabagent.core.database import ScheduledTask
    from crabagent.serve.scheduler import get_scheduler

    db = await _get_db()
    try:
        result = await db.execute(select(ScheduledTask).where(ScheduledTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return f"任务 #{task_id} 不存在"
        task.enabled = True
        await db.commit()
        await get_scheduler().add_task(task)
        return f"任务 #{task_id} '{task.name}' 已恢复，cron: `{task.cron_expression}`"
    except Exception as e:
        await db.rollback()
        return f"恢复任务失败：{e}"
    finally:
        await db.close()

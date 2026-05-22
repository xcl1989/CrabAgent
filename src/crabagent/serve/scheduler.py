from __future__ import annotations

import logging
import traceback
from datetime import UTC
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from crabagent.core.database import ScheduledTask, async_session_factory

logger = logging.getLogger(__name__)

_scheduler: SchedulerService | None = None


def get_scheduler() -> SchedulerService:
    global _scheduler
    if _scheduler is None:
        _scheduler = SchedulerService()
    return _scheduler


class SchedulerService:
    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self._job_ids: dict[int, str] = {}

    async def start(self):
        self._scheduler.start()
        tasks = await self._load_tasks()
        for task in tasks:
            await self.add_task(task)
        logger.info("Scheduler started with %d tasks", len(tasks))

    async def shutdown(self):
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    async def _load_tasks(self) -> list[ScheduledTask]:
        async with async_session_factory() as db:
            result = await db.execute(
                select(ScheduledTask).where(ScheduledTask.enabled.is_(True))
            )
            return list(result.scalars().all())

    def _parse_cron(self, expression: str) -> CronTrigger:
        parts = expression.strip().split()
        if len(parts) != 5:
            raise ValueError(f"cron 表达式必须包含5个字段，当前: '{expression}'")
        return CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
            timezone="Asia/Shanghai",
        )

    async def add_task(self, task: ScheduledTask) -> None:
        if not task.enabled:
            return
        self.remove_task(task.id)
        try:
            trigger = self._parse_cron(task.cron_expression)
        except Exception as e:
            logger.warning("Invalid cron for task #%d: %s", task.id, e)
            return
        job = self._scheduler.add_job(
            self._execute,
            trigger=trigger,
            args=[task.id],
            id=f"st_{task.id}",
            replace_existing=True,
        )
        self._job_ids[task.id] = job.id
        if job.next_run_time:
            async with async_session_factory() as db:
                result = await db.execute(select(ScheduledTask).where(ScheduledTask.id == task.id))
                t = result.scalar_one_or_none()
                if t:
                    t.next_run_at = job.next_run_time
                    await db.commit()
        logger.info("Task #%d '%s' scheduled, next: %s", task.id, task.name, job.next_run_time)

    def remove_task(self, task_id: int) -> None:
        job_id = self._job_ids.pop(task_id, None)
        if job_id and self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
            logger.info("Task #%d removed from scheduler", task_id)

    async def _execute(self, task_id: int):

        async with async_session_factory() as db:
            result = await db.execute(select(ScheduledTask).where(ScheduledTask.id == task_id))
            task = result.scalar_one_or_none()
            if not task:
                logger.warning("Task #%d not found, skipping", task_id)
                return

            logger.info("Executing task #%d: %s", task_id, task.name)

            try:
                session_id = await self._run_agent(task)
                task.last_status = "success"
                task.last_error = ""
                task.last_conversation_id = session_id
                task.last_run_at = utcnow()
                await db.commit()

                await self._create_notification(
                    db, task.user_id, task.name, "任务执行完成", session_id
                )
                logger.info("Task #%d completed, conversation: %s", task_id, session_id)
            except Exception as e:
                task.last_status = "error"
                task.last_error = str(e)[:500]
                task.last_run_at = utcnow()
                await db.commit()

                await self._create_notification(
                    db, task.user_id, task.name, f"执行失败: {str(e)[:200]}", ""
                )
                logger.error("Task #%d failed: %s\n%s", task_id, e, traceback.format_exc())

    async def _run_agent(self, task: ScheduledTask) -> str:
        from crabagent.core.agent.context import AgentContext
        from crabagent.core.agent.loop import run_agent
        from crabagent.core.agent.tools.registry import registry
        from crabagent.core.config import settings

        workspace = Path.cwd().resolve()
        model = task.model or ""
        system_prompt = (
            f"你正在执行一个定时任务：{task.name}。"
            "请完成任务后输出简要的完成说明。"
            f"工作目录: {workspace}"
        )

        context = AgentContext(
            workspace=workspace,
            tool_registry=registry,
            max_iterations=settings.max_iterations,
            model=model or None,
            system_prompt=system_prompt,
        )

        from crabagent.core.agent.skill.loader import discover_skills, register_skill_tool
        skill_dirs = settings.skill_discovery_dirs()
        skills = discover_skills(skill_dirs)
        if skills:
            register_skill_tool(context.tool_registry, skills)

        from crabagent.core.molt.tools import register_molt_tools
        register_molt_tools(context.tool_registry)

        from crabagent.core.todo.tools import register_todo_tools
        register_todo_tools(context.tool_registry)

        from crabagent.core.tool_loader import discover_and_register_tools
        discover_and_register_tools(context.tool_registry, workspace)

        try:
            from crabagent.core.mcp.client import MCPClientManager
            from crabagent.core.mcp.tools import register_mcp_tools

            mcp_manager = MCPClientManager()
            await mcp_manager.start_all()
            register_mcp_tools(context.tool_registry, mcp_manager)
            context.metadata["_mcp_manager"] = mcp_manager
        except Exception:
            pass

        settings.auto_approve_tools = True

        ctx_conv_id = _generate_session_id()
        context.metadata["session_id"] = ctx_conv_id
        context.metadata["branch_id"] = "main"

        conversation_id = await _create_conversation(task.user_id, task.name, str(workspace), model)
        context.metadata["_db_conversation_id"] = conversation_id

        try:
            await run_agent(context, task.prompt)
        finally:
            browser_mgr = context.metadata.get("_browser_manager")
            if browser_mgr:
                try:
                    await browser_mgr.close()
                except Exception:
                    pass
            mcp_mgr = context.metadata.get("_mcp_manager")
            if mcp_mgr:
                try:
                    await mcp_mgr.stop_all()
                except Exception:
                    pass
            settings.auto_approve_tools = False

        return ctx_conv_id

    async def _create_notification(self, db, user_id: int, title: str, body: str, conversation_id: str):
        from crabagent.core.database import Notification

        notif = Notification(
            user_id=user_id,
            title=title,
            body=body,
            conversation_id=conversation_id,
        )
        db.add(notif)
        await db.commit()


def utcnow():
    from datetime import datetime
    return datetime.now(UTC)


def _generate_session_id() -> str:
    import secrets
    return secrets.token_hex(16)


async def _create_conversation(user_id: int, title: str, workspace: str, model: str) -> int:
    from crabagent.core.database import Conversation

    async with async_session_factory() as db:
        conv = Conversation(
            session_id=_generate_session_id(),
            user_id=user_id,
            title=title[:500],
            workspace=workspace,
            model=model,
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        return conv.id

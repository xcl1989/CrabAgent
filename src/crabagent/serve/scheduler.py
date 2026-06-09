from __future__ import annotations

import logging
import traceback
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
    _EMAIL_POLL_JOB_ID = "email_poll"

    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self._job_ids: dict[int, str] = {}
        self._email_polling_users: dict[int, int] = {}  # user_id -> interval_seconds
        self._processed_message_ids: set[str] = set()  # dedup across poll cycles
        self._poll_failures: dict[int, int] = {}  # user_id -> consecutive failure count

    async def start(self):
        self._scheduler.start()
        tasks = await self._load_tasks()
        for task in tasks:
            await self.add_task(task)
        logger.info("Scheduler started with %d tasks", len(tasks))

        # Start email polling for all enabled configs
        await self.start_email_polling_all()

    async def shutdown(self):
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    async def _load_tasks(self) -> list[ScheduledTask]:
        async with async_session_factory() as db:
            result = await db.execute(select(ScheduledTask).where(ScheduledTask.enabled.is_(True)))
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
            timezone=_get_local_tz(),
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
            next_run_naive = job.next_run_time.replace(tzinfo=None)
            async with async_session_factory() as db:
                result = await db.execute(select(ScheduledTask).where(ScheduledTask.id == task.id))
                t = result.scalar_one_or_none()
                if t:
                    t.next_run_at = next_run_naive
                    await db.commit()
        logger.info("Task #%d '%s' scheduled, next: %s", task.id, task.name, job.next_run_time)

    def remove_task(self, task_id: int) -> None:
        job_id = self._job_ids.pop(task_id, None)
        if job_id and self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
            logger.info("Task #%d removed from scheduler", task_id)

    async def _execute(self, task_id: int):
        logger.info("[ST] _execute called, task_id=%d", task_id)

        async with async_session_factory() as db:
            result = await db.execute(select(ScheduledTask).where(ScheduledTask.id == task_id))
            task = result.scalar_one_or_none()
            if not task:
                logger.warning("[ST] Task #%d not found, skipping", task_id)
                return
            task_user_id = task.user_id
            task_name = task.name

        logger.info("[ST] Task #%d found: %s, user_id=%d", task_id, task_name, task_user_id)

        try:
            import asyncio

            logger.info("[ST] Task #%d: calling _run_agent", task_id)
            session_id = await asyncio.wait_for(self._run_agent(task), timeout=600)
            logger.info("[ST] Task #%d: _run_agent returned, session_id=%s", task_id, session_id)
        except TimeoutError:
            logger.error("[ST] Task #%d: _run_agent timed out (600s)", task_id)
        except Exception as e:
            logger.error("[ST] Task #%d: _run_agent failed: %s\n%s", task_id, e, traceback.format_exc())

        await self._refresh_next_run(task_id)

    async def _run_agent(self, task: ScheduledTask) -> str:
        from crabagent.core.agent.context import AgentContext
        from crabagent.core.agent.loop import run_agent
        from crabagent.core.agent.tools.registry import registry
        from crabagent.core.config import settings

        workspace = Path.cwd().resolve()
        default_model = settings.default_model
        # Check database settings override
        try:
            from crabagent.core.database import AppSetting, async_session_factory
            from sqlalchemy import select
            async with async_session_factory() as _sdb:
                _r = await _sdb.execute(select(AppSetting).where(AppSetting.key == "default_model"))
                _row = _r.scalar_one_or_none()
                if _row and _row.value:
                    default_model = _row.value
        except Exception:
            pass
        model = task.model or default_model
        system_prompt = f"你正在执行一个定时任务：{task.name}。请完成任务后输出简要的完成说明。工作目录: {workspace}"

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

        from crabagent.core.task.tools import register_task_tools

        register_task_tools(context.tool_registry)

        from crabagent.core.meeting.tools import register_meeting_tools

        register_meeting_tools(context.tool_registry)

        from crabagent.core.mail.tools import register_mail_tools

        register_mail_tools(context.tool_registry)

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

        conversation_id = await _create_conversation(task.user_id, task.name, str(workspace), model, ctx_conv_id)
        logger.info("[ST] conversation created, id=%d, session=%s", conversation_id, ctx_conv_id)
        context.metadata["_db_conversation_id"] = conversation_id

        from crabagent.serve.services.persistence import PersistenceListener

        persistence = PersistenceListener(conversation_id=conversation_id, branch_id="main")
        context.event_bus.subscribe(persistence.on_event)
        logger.info("[ST] PersistenceListener subscribed")

        from crabagent.core.agent.run_recorder import RunRecorder

        run_recorder = RunRecorder(user_id=task.user_id, session_id=ctx_conv_id, model=model)
        context.event_bus.subscribe(run_recorder.on_event)

        agent_error = None
        try:
            logger.info("[ST] calling run_agent, prompt=%.100s", task.prompt[:100])
            await run_agent(context, task.prompt)
            logger.info("[ST] run_agent finished, iterations=%d", context.iteration)
        except Exception as e:
            logger.error("[ST] run_agent error: %s", e)
            agent_error = e

        await self._commit_task_status(task.id, ctx_conv_id, agent_error)

        if agent_error:
            try:
                await self._create_notification(task.user_id, task.name, f"执行失败: {str(agent_error)[:200]}", "")
            except Exception:
                pass
        else:
            try:
                await self._create_notification(task.user_id, task.name, "任务执行完成", ctx_conv_id)
            except Exception:
                pass

        browser_mgr = context.metadata.get("_browser_manager")
        if browser_mgr:
            try:
                await browser_mgr.close()
            except Exception:
                pass
        mcp_mgr = context.metadata.get("_mcp_manager")
        if mcp_mgr:
            try:
                import asyncio as _asyncio

                await _asyncio.wait_for(mcp_mgr.stop_all(), timeout=10)
            except Exception:
                pass
        settings.auto_approve_tools = False
        logger.info("[ST] cleanup done, returning session_id=%s", ctx_conv_id)

        return ctx_conv_id

    async def _commit_task_status(self, task_id: int, conversation_id: str, error: Exception | None):
        async with async_session_factory() as db:
            result = await db.execute(select(ScheduledTask).where(ScheduledTask.id == task_id))
            t = result.scalar_one_or_none()
            if not t:
                return
            if error:
                t.last_status = "error"
                t.last_error = str(error)[:500]
            else:
                t.last_status = "success"
                t.last_error = ""
            t.last_conversation_id = conversation_id
            t.last_run_at = utcnow()
            await db.commit()
            logger.info("[ST] Task #%d status committed: %s", task_id, t.last_status)

    async def _refresh_next_run(self, task_id: int):
        job_id = self._job_ids.get(task_id)
        if not job_id:
            return
        job = self._scheduler.get_job(job_id)
        if not job or not job.next_run_time:
            return
        next_run_naive = job.next_run_time.replace(tzinfo=None)
        async with async_session_factory() as db:
            result = await db.execute(select(ScheduledTask).where(ScheduledTask.id == task_id))
            t = result.scalar_one_or_none()
            if t:
                t.next_run_at = next_run_naive
                await db.commit()
        logger.info("[ST] Task #%d next_run_at refreshed to %s", task_id, next_run_naive)

    async def _create_notification(self, user_id: int, title: str, body: str, conversation_id: str):
        from crabagent.core.database import Notification

        logger.info("[ST] _create_notification: user_id=%d, title=%s, conv=%s", user_id, title, conversation_id)
        try:
            async with async_session_factory() as db:
                notif = Notification(
                    user_id=user_id,
                    title=title,
                    body=body,
                    conversation_id=conversation_id,
                )
                db.add(notif)
                await db.commit()
            logger.info("[ST] notification created successfully, id=%d", notif.id)
        except Exception as e:
            logger.error("[ST] _create_notification FAILED: %s", e, exc_info=True)

    # ---- Email polling ----

    async def start_email_polling_all(self):
        """Load all enabled email configs and start interval polling."""
        from crabagent.core.database import EmailConfig

        async with async_session_factory() as db:
            result = await db.execute(
                select(EmailConfig).where(EmailConfig.enabled.is_(True))
            )
            configs = list(result.scalars().all())

        for cfg in configs:
            if cfg.imap_host:
                self.start_email_poll_for_user(cfg.user_id, cfg.check_interval)

    def start_email_poll_for_user(self, user_id: int, interval_seconds: int):
        """Start or restart email polling for a specific user."""
        # Ensure scheduler is running
        if not self._scheduler.running:
            self._scheduler.start()
        self._stop_email_poll_for_user(user_id)
        if interval_seconds < 30:
            interval_seconds = 30  # minimum 30s to avoid hammering IMAP

        job = self._scheduler.add_job(
            self._poll_emails,
            "interval",
            seconds=interval_seconds,
            args=[user_id],
            id=f"{self._EMAIL_POLL_JOB_ID}_{user_id}",
            replace_existing=True,
        )
        self._email_polling_users[user_id] = interval_seconds
        logger.info(
            "[EmailPoll] Started polling for user %d every %ds, next: %s",
            user_id, interval_seconds, job.next_run_time,
        )

    def stop_email_poll_for_user(self, user_id: int):
        """Stop email polling for a specific user."""
        self._stop_email_poll_for_user(user_id)

    def _stop_email_poll_for_user(self, user_id: int):
        job_id = f"{self._EMAIL_POLL_JOB_ID}_{user_id}"
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
        self._email_polling_users.pop(user_id, None)

    async def _poll_emails(self, user_id: int):
        """Called periodically: check new emails → match project → generate reply draft → notify."""
        from crabagent.core.mail.handler import check_new_emails

        logger.debug("[EmailPoll] Checking emails for user %d", user_id)
        try:
            emails = await check_new_emails(user_id, limit=10)
        except Exception as e:
            logger.error("[EmailPoll] Failed for user %d: %s", user_id, e)
            self._poll_failures[user_id] = self._poll_failures.get(user_id, 0) + 1
            fails = self._poll_failures[user_id]
            if fails == 5:
                await self._create_notification(
                    user_id,
                    "📬 Email Poll Failed",
                    f"Email polling has failed {fails} consecutive times. Please check your email configuration.\n\nError: {e}",
                    "",
                )
            return

        # Reset failure counter on success
        self._poll_failures[user_id] = 0

        if not emails:
            return

        # Dedup: skip emails already processed in earlier poll cycles
        new_emails = [e for e in emails if e.get("raw_message_id") not in self._processed_message_ids]
        if not new_emails:
            logger.debug("[EmailPoll] All %d emails already processed, skipping", len(emails))
            return

        logger.info("[EmailPoll] User %d has %d new emails (%d already seen)",
                     user_id, len(new_emails), len(emails) - len(new_emails))

        # Track processed message IDs (cap set size to avoid memory leak)
        for e in new_emails:
            if e.get("raw_message_id"):
                self._processed_message_ids.add(e["raw_message_id"])
        if len(self._processed_message_ids) > 1000:
            self._processed_message_ids = set(list(self._processed_message_ids)[-500:])

        # Load LLM params for matching & reply draft
        model, llm_params = await self._get_llm_params()

        # Load user locale for notification text
        locale = await self._get_user_locale(user_id)

        # Load projects once for all emails
        projects = await self._get_user_projects(user_id)

        for email in new_emails[:5]:
            subject = email.get("subject", "(no subject)")
            sender = email.get("from", "?")
            body = email.get("body", "")

            # 1. Match to project
            project_ctx = ""
            match_info = ""
            if projects:
                try:
                    from crabagent.core.mail.matcher import match_email_to_project, build_project_context

                    match = await match_email_to_project(
                        subject=subject,
                        body_snippet=body[:300],
                        sender=sender,
                        projects=projects,
                        model=model,
                        llm_params=llm_params if len(projects) > 2 else None,
                    )
                    if match:
                        match_info = _t("emailPoll.projectMatch", locale, project=match['project'], confidence=match['confidence'])
                        project_tasks = await self._get_project_tasks(user_id, match["project"])
                        project_ctx = build_project_context(match["project"], project_tasks)
                except Exception as e:
                    logger.warning("[EmailPoll] Project match failed: %s", e)

            # 2. Generate reply draft
            draft = ""
            try:
                draft = await self._generate_reply_draft(
                    to=sender,
                    original_subject=subject,
                    original_body=body[:1000],
                    project_context=project_ctx,
                    model=model,
                    llm_params=llm_params,
                )
            except Exception as e:
                logger.warning("[EmailPoll] Reply draft failed: %s", e)
                draft = _t("emailPoll.draftFailed", locale, error=str(e))

            # 3. Create a conversation for email detail view (BEFORE task extraction,
            #    so tasks can be linked to the conversation)
            email_conv_session_id = ""
            try:
                email_conv_session_id = _generate_session_id()
                conv_id = await _create_conversation(
                    user_id=user_id,
                    title=f"📧 {subject[:80]}",
                    workspace=str(Path.cwd().resolve()),
                    model=model,
                    session_id=email_conv_session_id,
                )
                # Store email content + draft reply as messages in this conversation
                from crabagent.core.database import Message as DbMessage

                async with async_session_factory() as _db:
                    email_msg = DbMessage(
                        conversation_id=conv_id,
                        sequence=0,
                        role="user",
                        content=_build_email_detail_content(subject, sender, body, match_info),
                        branch_id="main",
                    )
                    _db.add(email_msg)
                    if draft:
                        draft_msg = DbMessage(
                            conversation_id=conv_id,
                            sequence=1,
                            role="assistant",
                            content=f"📝 **回信草稿**\n\n{draft}\n\n_可以使用 `email_send` 发送草稿，或让我修改。_",
                            branch_id="main",
                        )
                        _db.add(draft_msg)
                    await _db.commit()
            except Exception as e:
                logger.warning("[EmailPoll] Failed to create email detail conversation: %s", e)
                email_conv_session_id = ""

            # 2.5 Extract tasks from email via LLM (with conversation session_id)
            created_tasks = []
            try:
                created_tasks = await self._extract_tasks_from_email(
                    user_id=user_id,
                    subject=subject,
                    body=body[:3000],
                    sender=sender,
                    project_context=project_ctx,
                    source_session=email_conv_session_id,
                    model=model,
                    llm_params=llm_params,
                )
            except Exception as e:
                logger.warning("[EmailPoll] Task extraction failed: %s", e)

            # 4. Build rich notification body
            notif_lines = [f"📧 **{subject}**", _t("emailPoll.from", locale, sender=sender)]
            if match_info:
                notif_lines.append(f"   {match_info}")
            # Original email preview
            body_preview = (body[:300] + "…") if len(body) > 300 else body
            notif_lines.append("")
            notif_lines.append("📄 **原文**")
            notif_lines.append(body_preview)
            if draft:
                notif_lines.append("")
                notif_lines.append(f"📝 **{_t('emailPoll.draftReply', locale)}**")
                notif_lines.append(draft)
            if created_tasks:
                notif_lines.append("")
                notif_lines.append(f"✅ **{len(created_tasks)} 个任务已自动创建:**")
                for ct in created_tasks:
                    prio_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(ct.get("priority", "medium"), "🟡")
                    notif_lines.append(f"  {prio_icon} {ct['title']} (task #{ct['id']})")
                    if ct.get("deadline"):
                        notif_lines.append(f"     📅 {ct['deadline'][:10]}")
            notif_lines.append("")
            notif_lines.append(_t("emailPoll.actionHint", locale))

            body_text = "\n".join(notif_lines)
            try:
                title = _t("emailPoll.newEmail", locale, subject=subject[:80])
                await self._create_notification(user_id, title, body_text, email_conv_session_id)
            except Exception as e:
                logger.error("[EmailPoll] Notification failed for user %d: %s", user_id, e)

        # Summary if more than 5
        if len(new_emails) > 5:
            extra = _t("emailPoll.moreEmails", locale, count=len(new_emails) - 5)
            try:
                await self._create_notification(user_id, _t("emailPoll.moreEmailsTitle", locale), extra, "")
            except Exception:
                pass

    async def _get_llm_params(self) -> tuple[str, dict]:
        """Get LLM model and params from default config or most recently used provider+model pair."""
        try:
            from crabagent.core.provider_store import get_provider
            from crabagent.core.database import async_session_factory, Conversation, AppSetting
            from sqlalchemy import select
            from crabagent.core.config import settings

            # Check database settings first (user-set via frontend), fall back to env/code default
            default_model = settings.default_model
            default_provider_name = ""
            async with async_session_factory() as db:
                for key in ("default_model", "default_model_provider"):
                    result = await db.execute(
                        select(AppSetting).where(AppSetting.key == key)
                    )
                    row = result.scalar_one_or_none()
                    if row and row.value:
                        if key == "default_model":
                            default_model = row.value
                        elif key == "default_model_provider":
                            default_provider_name = row.value

            # Get the most recently used provider+model from conversations
            async with async_session_factory() as db:
                result = await db.execute(
                    select(Conversation.model, Conversation.provider)
                    .where(Conversation.model.isnot(None), Conversation.model != "")
                    .order_by(Conversation.updated_at.desc())
                    .limit(1)
                )
                row = result.first()

            if not row or not row[0]:
                # Use default model + try saved provider
                if default_provider_name:
                    provider = await get_provider(default_provider_name)
                    if provider:
                        params: dict = {"api_key": provider.api_key}
                        if provider.base_url:
                            params["api_base"] = provider.base_url
                            params["custom_llm_provider"] = "openai"
                        return default_model, params
                return default_model, {}

            model = row[0]
            provider_name = row[1]

            # Try to get the matching provider first, fall back to default
            provider = None
            if provider_name:
                provider = await get_provider(provider_name)
            if not provider:
                from crabagent.core.provider_store import get_default_provider
                provider = await get_default_provider()
            if not provider:
                return model, {}

            params: dict = {"api_key": provider.api_key}
            if provider.base_url:
                params["api_base"] = provider.base_url
                params["custom_llm_provider"] = "openai"

            return model, params
        except Exception:
            from crabagent.core.config import settings
            return settings.default_model, {}

    async def _get_user_locale(self, user_id: int) -> str:
        """Get user's locale setting from database."""
        try:
            from crabagent.core.database import User, async_session_factory
            from sqlalchemy import select
            async with async_session_factory() as db:
                result = await db.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()
                if user and user.locale:
                    return user.locale
        except Exception:
            pass
        from crabagent.core.config import settings
        return settings.language or "en"

    async def _get_user_projects(self, user_id: int) -> list[dict]:
        """Load user's projects for email matching."""
        try:
            from crabagent.core.task.store import list_projects
            from crabagent.core.database import async_session_factory

            async with async_session_factory() as db:
                return await list_projects(db, user_id)
        except Exception:
            return []

    async def _get_project_tasks(self, user_id: int, project: str) -> list[dict]:
        """Load tasks for a specific project."""
        try:
            from crabagent.core.task.store import list_tasks
            from crabagent.core.database import async_session_factory

            async with async_session_factory() as db:
                return await list_tasks(db, user_id, "all", project)
        except Exception:
            return []

    async def _generate_reply_draft(
        self,
        to: str,
        original_subject: str,
        original_body: str,
        project_context: str,
        model: str,
        llm_params: dict,
    ) -> str:
        """Generate a concise reply draft using LLM."""
        import litellm

        tone_guides = {
            "concise": "Keep the reply brief and to the point. 2-3 sentences max.",
            "detailed": "Provide a thorough reply with context and details.",
            "formal": "Use professional, formal language suitable for business communication.",
            "friendly": "Use a warm, casual tone.",
        }

        prompt = (
            "You are helping draft an email reply.\n\n"
            f"**Original email:**\n"
            f"  Subject: {original_subject[:200]}\n"
            f"  From: {to}\n"
            f"  Body:\n{original_body[:1000]}\n\n"
        )

        if project_context:
            prompt += f"**Project context (reference this naturally if relevant):**\n{project_context}\n\n"

        prompt += (
            f"**Tone:** {tone_guides['concise']}\n\n"
            "Generate a reply draft. Only output the reply body text, "
            "no subject line or metadata. Write in the same language as the original email."
        )

        response = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.5,
            **llm_params,
        )
        return (response.choices[0].message.content or "").strip()

    async def _extract_tasks_from_email(
        self,
        user_id: int,
        subject: str,
        body: str,
        sender: str,
        project_context: str,
        source_session: str,
        model: str,
        llm_params: dict,
    ) -> list[dict]:
        """Use LLM to analyze email and auto-create tasks if action items detected.

        Returns list of created task dicts (empty list if no tasks detected).
        """
        import datetime
        import json
        import litellm

        prompt = (
            "You are an AI assistant that analyzes emails and extracts action items.\n\n"
            f"**Email:**\n"
            f"  Subject: {subject[:200]}\n"
            f"  From: {sender}\n"
            f"  Body:\n{body[:3000]}\n\n"
        )
        if project_context:
            prompt += f"**Project context:**\n{project_context}\n\n"

        today = datetime.datetime.now().strftime("%Y-%m-%d")
        prompt += (
            f"Today's date: {today}\n\n"
            "Analyze this email. If it contains any tasks, action items, to-dos, "
            "meeting arrangements, or things the recipient needs to do, extract them.\n\n"
            "For each action item, identify:\n"
            "- title (required, short description of the task)\n"
            "- description (optional, longer context from the email)\n"
            "- assignee (optional, who is responsible — default to the email recipient if unclear)\n"
            "- deadline (optional, date in YYYY-MM-DD format. If relative like 'next Friday' or 'tomorrow' or '4pm', compute from today)\n"
            "- priority (optional: high/medium/low. Default: medium)\n\n"
            "Be conservative: only extract items that are clearly actionable tasks or commitments. "
            "Ignore general information, newsletters, or automated notifications.\n\n"
            "If no action items found, set action_items to an empty array.\n\n"
            "Respond with JSON only, using this exact format:\n"
            "{\n"
            '  "summary": "Brief analysis of what needs to be done",\n'
            '  "action_items": [\n'
            "    {\n"
            '      "title": "...",\n'
            '      "description": "...",\n'
            '      "assignee": "...",\n'
            '      "deadline": "YYYY-MM-DD",\n'
            '      "priority": "medium"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "IMPORTANT: Output ONLY valid JSON, no other text."
        )

        try:
            response = await litellm.acompletion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
                temperature=0.1,
                **llm_params,
            )
            raw = response.choices[0].message.content or "{}"
        except Exception as e:
            logger.warning("[EmailPoll] Task extraction LLM call failed: %s", e)
            return []

        # Parse JSON
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                start = cleaned.find("{")
                end = cleaned.rfind("}")
                if start >= 0 and end > start:
                    cleaned = cleaned[start: end + 1]
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("[EmailPoll] Task extraction JSON parse failed: raw=%s", raw[:200])
            return []

        action_items = data.get("action_items", [])
        if not action_items:
            return []

        # Create tasks
        from crabagent.core.task.store import add_task as _add_task

        created_tasks = []
        async with async_session_factory() as db:
            for item in action_items:
                title = item.get("title", "").strip()
                if not title:
                    continue
                deadline = None
                dl_str = item.get("deadline", "")
                if dl_str:
                    try:
                        deadline = datetime.datetime.strptime(dl_str[:10], "%Y-%m-%d")
                    except ValueError:
                        pass
                try:
                    t = await _add_task(
                        db,
                        user_id=user_id,
                        title=title,
                        description=item.get("description", ""),
                        assignee=item.get("assignee", ""),
                        deadline=deadline,
                        source="email",
                        source_ref=subject[:100],
                        source_session=source_session,
                        project="",
                        priority=item.get("priority", "medium"),
                    )
                    created_tasks.append(t)
                    logger.info("[EmailPoll] Created task #%d from email '%s': %s", t["id"], subject[:50], title)
                except Exception as e:
                    logger.error("[EmailPoll] Failed to create task: %s", e)

        return created_tasks


def _build_email_detail_content(subject: str, sender: str, body: str, match_info: str) -> str:
    """Build the email detail content stored in conversation for '查看详情'."""
    lines = [
        f"📧 **{subject}**",
        f"   来自：{sender}",
        "",
        "--- 邮件原文 ---",
        body[:5000],
    ]
    if match_info:
        lines.append("")
        lines.append(f"📁 {match_info}")
    return "\n".join(lines)


_EMAIL_POLL_I18N: dict[str, dict[str, str]] = {
    "en": {
        "emailPoll.newEmail": "📬 New Email: {subject}",
        "emailPoll.from": "   From: {sender}",
        "emailPoll.projectMatch": "📁 Project: {project} ({confidence})",
        "emailPoll.draftReply": "Draft reply",
        "emailPoll.draftFailed": "_(Draft generation failed: {error})_",
        "emailPoll.actionHint": "_Use `email_send` to send the draft, or ask me to revise it._",
        "emailPoll.moreEmailsTitle": "📬 More Emails",
        "emailPoll.moreEmails": "… and {count} more new email(s)",
    },
    "zh-CN": {
        "emailPoll.newEmail": "📬 新邮件：{subject}",
        "emailPoll.from": "   来自：{sender}",
        "emailPoll.projectMatch": "📁 关联项目：{project}（{confidence}）",
        "emailPoll.draftReply": "回信草稿",
        "emailPoll.draftFailed": "_(草稿生成失败：{error})_",
        "emailPoll.actionHint": "_可以使用 `email_send` 发送草稿，或让我修改。_",
        "emailPoll.moreEmailsTitle": "📬 更多邮件",
        "emailPoll.moreEmails": "…还有 {count} 封新邮件",
    },
}


def _t(key: str, locale: str, **kwargs) -> str:
    """Simple i18n for email poll notifications."""
    lang = locale if locale in _EMAIL_POLL_I18N else "en"
    template = _EMAIL_POLL_I18N[lang].get(key) or _EMAIL_POLL_I18N["en"].get(key) or key
    return template.format_map(kwargs)


def utcnow():
    from datetime import datetime

    return datetime.now()


def _get_local_tz():
    try:
        import tzlocal

        return tzlocal.get_localzone()
    except Exception:
        from datetime import datetime

        return datetime.now().astimezone().tzinfo


def _generate_session_id() -> str:
    import secrets

    return secrets.token_hex(16)


async def _create_conversation(user_id: int, title: str, workspace: str, model: str, session_id: str) -> int:
    from crabagent.core.database import Conversation

    async with async_session_factory() as db:
        conv = Conversation(
            session_id=session_id,
            user_id=user_id,
            title=title[:500],
            workspace=workspace,
            model=model,
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        return conv.id

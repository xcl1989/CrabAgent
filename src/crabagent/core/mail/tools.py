from __future__ import annotations

import datetime
import logging

logger = logging.getLogger(__name__)


def _fmt_task_list(tasks: list[dict], title: str) -> str:
    if not tasks:
        return ""
    lines = [f"**{title}:**", ""]
    for i, t in enumerate(tasks, 1):
        pri = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
            t.get("priority", "medium"), "🟡"
        )
        line = f"  {i}. {pri} **{t['title']}**"
        if t.get("assignee"):
            line += f" (👤 {t['assignee']})"
        if t.get("deadline"):
            line += f" 📅 {t['deadline'][:10]}"
        if t.get("project"):
            line += f" [{t['project']}]"
        lines.append(line)
    lines.append("")
    return "\n".join(lines)


def register_mail_tools(registry):
    @registry.register(
        name="email_send",
        description=(
            "Send an email via the configured SMTP server. "
            "Use when the user asks to send an email, reply to someone, "
            "or send a notification. Supports file attachments and HTML body. "
            "Requires email configuration to be set up."
        ),
        parameters={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject",
                },
                "body": {
                    "type": "string",
                    "description": "Email body text (plain text by default, HTML if html=true)",
                },
                "attachments": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths to attach (e.g. [\"/path/to/report.pdf\"])",
                },
                "html": {
                    "type": "boolean",
                    "description": "If true, body is treated as HTML. Default: false.",
                },
            },
            "required": ["to", "subject", "body"],
        },
    )
    async def email_send(
        to: str,
        subject: str,
        body: str,
        attachments: list[str] | None = None,
        html: bool = False,
        context=None,
    ) -> str:
        from crabagent.core.mail.handler import send_email as _send

        user_id = 1
        if context:
            user_id = int(
                context.metadata.get("user_id", context.metadata.get("uid", 1))
            )

        result = await _send(
            to=to, subject=subject, body=body,
            user_id=user_id, attachments=attachments, html=html,
        )
        if result.get("status") == "ok":
            att_info = f" ({result.get('attachments', 0)} attachments)" if attachments else ""
            return f"✅ Email sent to **{to}**: {subject}{att_info}"
        else:
            return f"❌ Failed to send email: {result.get('message', 'Unknown error')}"

    @registry.register(
        name="email_check",
        description=(
            "Check for new (unseen) emails. "
            "Use when the user asks 'check my email', 'any new emails', "
            "or 'did I get any messages'. "
            "Returns a summary of unread emails. Requires email configuration."
        ),
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of emails to return (default: 5)",
                },
            },
        },
    )
    async def email_check(limit: int = 5, context=None) -> str:
        import asyncio

        from crabagent.core.mail.handler import check_new_emails as _check
        from crabagent.core.mail.matcher import match_email_to_project, build_project_context

        user_id = 1
        if context:
            user_id = int(
                context.metadata.get("user_id", context.metadata.get("uid", 1))
            )

        try:
            emails = await asyncio.wait_for(_check(user_id=user_id, limit=limit), timeout=45)
        except asyncio.TimeoutError:
            return "⏱️ Email check timed out. The IMAP connection may be slow or unreachable."
        except Exception as e:
            logger.error("email_check failed: %s", e)
            return f"❌ Email check failed: {e}"
        if not emails:
            return "📭 No new emails."

        # Load projects and resolve LLM params for matching
        from crabagent.core.config import settings

        projects = []
        model = settings.default_model
        llm_params: dict = {}
        try:
            from crabagent.core.database import async_session_factory
            from crabagent.core.task.store import list_projects as _list_projects

            async with async_session_factory() as db:
                projects = await _list_projects(db, user_id)
        except Exception:
            pass

        if context:
            try:
                from crabagent.core.provider_store import get_default_provider

                provider = await get_default_provider()
                if provider:
                    model = context.metadata.get("model", model)
                    llm_params = {"api_key": provider.api_key}
                    if provider.base_url:
                        llm_params["api_base"] = provider.base_url
                        llm_params["custom_llm_provider"] = "openai"
            except Exception:
                pass

        lines = [f"📧 **{len(emails)} new email(s):**", ""]
        for i, e in enumerate(emails, 1):
            subject = e.get("subject", "(no subject)")
            sender = e.get("from", "unknown")
            date = e.get("date", "")
            body = e.get("body", "")
            body_preview = body[:120].replace("\n", " ")

            lines.append(f"  {i}. **{subject}**")
            lines.append(f"     From: {sender}")
            lines.append(f"     Date: {date}")
            if body_preview:
                lines.append(
                    f"     {body_preview}…"
                    if len(body) > 120
                    else f"     {body_preview}"
                )

            # Try to match email to a project
            if projects:
                match = await match_email_to_project(
                    subject=subject,
                    body_snippet=body[:300],
                    sender=sender,
                    projects=projects,
                    model=model,
                    llm_params=llm_params if len(projects) > 2 else None,
                )
                if match:
                    confidence_icon = {"high": "🟢", "medium": "🟡", "low": "⚪"}.get(
                        match["confidence"], "🟡"
                    )
                    lines.append(f"     {confidence_icon} Project: **{match['project']}** ({match['confidence']})")

                    # Load project context
                    try:
                        from crabagent.core.database import async_session_factory
                        from crabagent.core.task.store import list_tasks as _list_tasks

                        async with async_session_factory() as db:
                            project_tasks = await _list_tasks(db, user_id, "all", match["project"])
                        ctx = build_project_context(match["project"], project_tasks)
                        # Indent context block
                        for cl in ctx.split("\n"):
                            lines.append(f"     {cl}")
                    except Exception:
                        pass

            lines.append("")

        return "\n".join(lines)

    @registry.register(
        name="email_send_draft",
        description=(
            "Send a draft or pending email. "
            "Use when the user reviews and approves a previously drafted email."
        ),
        parameters={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject",
                },
                "body": {
                    "type": "string",
                    "description": "Final email body text",
                },
                "attachments": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths to attach",
                },
            },
            "required": ["to", "subject", "body"],
        },
    )
    async def email_send_draft(
        to: str, subject: str, body: str,
        attachments: list[str] | None = None,
        context=None,
    ) -> str:
        from crabagent.core.mail.handler import send_email as _send

        user_id = 1
        if context:
            user_id = int(
                context.metadata.get("user_id", context.metadata.get("uid", 1))
            )

        result = await _send(
            to=to, subject=f"[Draft] {subject}", body=body,
            user_id=user_id, attachments=attachments,
        )
        if result.get("status") == "ok":
            att_info = f" ({result.get('attachments', 0)} attachments)" if attachments else ""
            return f"✅ Draft sent to **{to}**: {subject}{att_info}"
        else:
            return f"❌ Failed to send draft: {result.get('message', 'Unknown error')}"

    @registry.register(
        name="email_reply_draft",
        description=(
            "Generate a smart reply draft for an email, incorporating project context "
            "and task status if the email relates to a known project. "
            "Use when the user wants to reply to an email or asks for help drafting a response."
        ),
        parameters={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address (the sender of the original email)",
                },
                "original_subject": {
                    "type": "string",
                    "description": "Subject of the original email",
                },
                "original_body": {
                    "type": "string",
                    "description": "Body text of the original email",
                },
                "tone": {
                    "type": "string",
                    "description": "Tone of the reply: concise, detailed, formal, or friendly (default: concise)",
                    "enum": ["concise", "detailed", "formal", "friendly"],
                },
                "project_context": {
                    "type": "string",
                    "description": "Optional project context to include in the reply (e.g. task status)",
                },
                "additional_instructions": {
                    "type": "string",
                    "description": "Optional extra instructions from the user for the reply",
                },
            },
            "required": ["to", "original_subject", "original_body"],
        },
    )
    async def email_reply_draft(
        to: str,
        original_subject: str,
        original_body: str,
        tone: str = "concise",
        project_context: str = "",
        additional_instructions: str = "",
        context=None,
    ) -> str:
        import litellm

        from crabagent.core.mail.handler import send_email as _send

        user_id = 1
        from crabagent.core.config import settings

        model = settings.default_model
        llm_params: dict = {}
        if context:
            user_id = int(
                context.metadata.get("user_id", context.metadata.get("uid", 1))
            )
            try:
                from crabagent.core.provider_store import get_default_provider

                provider = await get_default_provider()
                if provider:
                    model = context.metadata.get("model", model)
                    llm_params = {"api_key": provider.api_key}
                    if provider.base_url:
                        llm_params["api_base"] = provider.base_url
                        llm_params["custom_llm_provider"] = "openai"
            except Exception:
                pass

        # Auto-detect project if not provided
        if not project_context:
            try:
                from crabagent.core.database import async_session_factory
                from crabagent.core.mail.matcher import match_email_to_project, build_project_context
                from crabagent.core.task.store import list_projects as _list_projects, list_tasks as _list_tasks

                async with async_session_factory() as db:
                    projects = await _list_projects(db, user_id)
                    if projects:
                        match = await match_email_to_project(
                            subject=original_subject,
                            body_snippet=original_body[:300],
                            sender=to,
                            projects=projects,
                            model=model,
                            llm_params=llm_params if len(projects) > 2 else None,
                        )
                        if match:
                            project_tasks = await _list_tasks(db, user_id, "all", match["project"])
                            project_context = build_project_context(match["project"], project_tasks)
            except Exception:
                pass

        # Build prompt
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

        if additional_instructions:
            prompt += f"**Additional instructions:** {additional_instructions}\n\n"

        prompt += (
            f"**Tone:** {tone_guides.get(tone, tone_guides['concise'])}\n\n"
            "Generate a reply draft. Only output the reply body text, "
            "no subject line or metadata. Write in the same language as the original email."
        )

        try:
            response = await litellm.acompletion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.5,
                **llm_params,
            )
            draft = (response.choices[0].message.content or "").strip()
        except Exception as e:
            logger.error(f"Reply draft generation failed: {e}")
            return f"❌ Failed to generate reply draft: {e}"

        if not draft:
            return "❌ Failed to generate reply draft: empty response"

        # Format result for the agent
        subject_reply = f"Re: {original_subject}"
        result_lines = [
            f"📝 **Reply draft generated:**",
            f"",
            f"> To: **{to}**",
            f"> Subject: **{subject_reply}**",
            f"",
            f"---",
            f"{draft}",
            f"---",
            f"",
            f"Review the draft above. To send it, use `email_send` with:",
            f"- to: `{to}`",
            f"- subject: `{subject_reply}`",
            f"- body: *(the draft text above)*",
        ]

        if project_context:
            result_lines.append(f"\n📎 _Context used: {project_context.split(chr(10))[0]}_")

        return "\n".join(result_lines)

    @registry.register(
        name="daily_digest",
        description=(
            "Generate and send a daily summary email with task status, overdue items, "
            "and upcoming deadlines. Use this when the user asks for a daily report, "
            "morning summary, or status update. Requires email configuration."
        ),
        parameters={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Email address to send the digest to.",
                },
            },
        },
    )
    async def daily_digest(to: str = "", context=None) -> str:
        from crabagent.core.database import async_session_factory
        from crabagent.core.mail.handler import get_config as _get_mail_cfg
        from crabagent.core.mail.handler import send_email as _send
        from crabagent.core.task.store import list_tasks as _list
        from crabagent.core.task.store import get_task_summary, list_tasks_due_soon

        user_id = 1
        if context:
            user_id = int(
                context.metadata.get("user_id", context.metadata.get("uid", 1))
            )

        cfg = await _get_mail_cfg(user_id)
        recipient = to or (cfg.imap_user if cfg else "")

        async with async_session_factory() as db:
            summary = await get_task_summary(db, user_id)
            overdue = await _list(db, user_id, "overdue")
            pending = await _list(db, user_id, "pending")
            due_soon = await list_tasks_due_soon(db, user_id, within_hours=24)
            done = await _list(db, user_id, "done")

        today = datetime.datetime.now().strftime("%Y-%m-%d %A")
        lines = [
            f"📋 **Daily Digest — {today}**",
            "",
            f"**Overview:**",
            f"  • Total tasks: {summary['total']}",
            f"  • Pending: {summary['pending']}",
            f"  • Overdue: {summary['overdue']}",
            f"  • Completed yesterday: {summary['done_today']}",
            "",
        ]
        if overdue:
            lines.append(_fmt_task_list(overdue, "🔴 Overdue Tasks"))
        if due_soon:
            lines.append(_fmt_task_list(due_soon, "⏰ Due Within 24 Hours"))
        if pending:
            lines.append(_fmt_task_list(pending[:10], "📌 Pending Tasks"))
        if summary["done_today"] > 0:
            lines.append(_fmt_task_list(done[:5], "✅ Recently Completed"))
        else:
            lines.append("_No tasks completed yesterday._\n")

        body = "\n".join(lines)

        if recipient:
            result = await _send(
                to=recipient,
                subject=f"Daily Digest — {today}",
                body=body,
                user_id=user_id,
            )
            if result.get("status") == "ok":
                return f"✅ Daily digest sent to **{recipient}**\n\n{body}"
            else:
                return (
                    f"❌ Failed to send: {result.get('message', '')}\n\n{body}"
                )
        else:
            return (
                f"📋 **Daily Digest Preview**\n\n{body}"
                "\n*(No email configured)*"
            )

    @registry.register(
        name="task_remind",
        description=(
            "Check for tasks approaching their deadline and send email reminders. "
            "Use for scheduled checks (e.g., every morning at 8 AM) to automatically "
            "remind about tasks due within 24 hours. Requires email configuration."
        ),
        parameters={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Email address to send reminders to.",
                },
            },
        },
    )
    async def task_remind(to: str = "", context=None) -> str:
        from crabagent.core.database import async_session_factory
        from crabagent.core.mail.handler import get_config as _get_mail_cfg
        from crabagent.core.mail.handler import send_email as _send
        from crabagent.core.task.store import list_tasks as _list
        from crabagent.core.task.store import list_tasks_due_soon

        user_id = 1
        if context:
            user_id = int(
                context.metadata.get("user_id", context.metadata.get("uid", 1))
            )

        cfg = await _get_mail_cfg(user_id)
        recipient = to or (cfg.imap_user if cfg else "")

        async with async_session_factory() as db:
            due_soon = await list_tasks_due_soon(db, user_id, within_hours=24)
            overdue = await _list(db, user_id, "overdue")

        if not due_soon and not overdue:
            return "✅ No tasks need reminders."

        lines = ["⏰ **Task Reminder**", ""]
        if overdue:
            lines.append(
                _fmt_task_list(overdue, "🔴 Overdue — Needs Attention Now")
            )
        if due_soon:
            lines.append(
                _fmt_task_list(due_soon, "⏰ Due Within 24 Hours")
            )
        lines.append("— Sent by CrabAgent")
        body = "\n".join(lines)

        if recipient:
            result = await _send(
                to=recipient,
                subject=f"⏰ Task Reminder — {len(due_soon) + len(overdue)} task(s) need attention",
                body=body,
                user_id=user_id,
            )
            if result.get("status") == "ok":
                return f"✅ Reminder sent to **{recipient}**"
            else:
                return f"❌ Failed to send: {result.get('message', '')}"
        else:
            return f"📋 **Reminder Preview**\n\n{body}"

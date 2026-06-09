from __future__ import annotations

import datetime
import json
import logging

logger = logging.getLogger(__name__)


def register_meeting_tools(registry):
    @registry.register(
        name="meeting_process",
        description=(
            "Process meeting notes and extract action items. "
            "Automatically creates persistent tasks for each action item "
            "with assignee, deadline, and priority. "
            "Use when the user shares meeting notes, call notes, or discussion summaries."
        ),
        parameters={
            "type": "object",
            "properties": {
                "notes": {
                    "type": "string",
                    "description": "Meeting notes text (free form, bullet points, or structured notes)",
                },
                "meeting_title": {
                    "type": "string",
                    "description": "Optional meeting title or topic",
                },
            },
            "required": ["notes"],
        },
    )
    async def meeting_process(
        notes: str,
        meeting_title: str = "",
        context=None,
    ) -> str:
        import litellm

        from crabagent.core.database import async_session_factory
        from crabagent.core.task.store import add_task as _add_task

        # Resolve user_id
        user_id = 1
        if context:
            user_id = int(
                context.metadata.get("user_id", context.metadata.get("uid", 1))
            )

        # Resolve model/provider from context
        model = "gpt-4o"
        provider_name = None
        llm_params = {}
        if context:
            try:
                from crabagent.core.provider_store import get_default_provider

                provider = await get_default_provider()
                if provider:
                    model = context.metadata.get("model", model)
                    provider_name = provider.name
                    llm_params = {
                        "api_key": provider.api_key,
                    }
                    if provider.base_url:
                        llm_params["api_base"] = provider.base_url
                        llm_params["custom_llm_provider"] = "openai"
            except Exception:
                pass

        # Build extraction prompt
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        prompt = (
            f"You are an AI assistant that extracts action items from meeting notes.\n\n"
            f"Today's date: {today}\n\n"
            f"Meeting notes:\n{notes}\n\n"
            f"Extract all action items from these notes. "
            f"For each action item, identify:\n"
            f"- title (required, short description)\n"
            f"- description (optional, longer context)\n"
            f"- assignee (optional, who is responsible)\n"
            f"- deadline (optional, date in YYYY-MM-DD format. If relative like 'next Friday', compute from today={today})\n"
            f"- priority (optional: high/medium/low. Default: medium)\n\n"
            f"Also extract a brief meeting summary if possible.\n\n"
            f"Respond with JSON only, using this exact format:\n"
            f"{{\n"
            f'  "summary": "Brief meeting summary",\n'
            f'  "action_items": [\n'
            f"    {{\n"
            f'      "title": "...",\n'
            f'      "description": "...",\n'
            f'      "assignee": "...",\n'
            f'      "deadline": "YYYY-MM-DD",\n'
            f'      "priority": "medium"\n'
            f"    }}\n"
            f"  ]\n"
            f"}}\n\n"
            f"If there are no action items, set action_items to an empty array.\n"
            f"IMPORTANT: Output ONLY valid JSON, no other text."
        )

        try:
            response = await litellm.acompletion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4000,
                temperature=0.1,
                **llm_params,
            )
            raw = response.choices[0].message.content or "{}"
        except Exception as e:
            logger.error(f"Meeting LLM call failed: {e}")
            raw = '{"summary": "Failed to process meeting notes.", "action_items": []}'

        # Parse JSON response
        try:
            # Clean markdown code block if present
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                # Extract JSON from code block
                start = cleaned.find("{")
                end = cleaned.rfind("}")
                if start >= 0 and end > start:
                    cleaned = cleaned[start : end + 1]
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            data = {"summary": "Extraction completed.", "action_items": []}

        summary = data.get("summary", "Meeting processed.")
        action_items = data.get("action_items", [])

        # Create tasks
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
                        source="meeting",
                        source_ref=meeting_title or today,
                        project="",
                        priority=item.get("priority", "medium"),
                    )
                    created_tasks.append(t)
                except Exception as e:
                    logger.error(f"Failed to create task: {e}")

        # Format result
        title_line = f"📋 **{meeting_title or 'Meeting Notes'}**" if meeting_title else "📋 **Meeting Notes**"
        lines = [
            title_line,
            "",
            f"📝 {summary}",
            "",
        ]

        if created_tasks:
            lines.append(f"✅ **{len(created_tasks)} action items created:**")
            lines.append("")
            for i, t in enumerate(created_tasks, 1):
                pri_dot = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                    t.get("priority", "medium"), "🟡"
                )
                line = f"  {i}. {pri_dot} **{t['title']}** (task #{t['id']})"
                if t.get("assignee"):
                    line += f" 👤 {t['assignee']}"
                if t.get("deadline"):
                    line += f" 📅 {t['deadline'][:10]}"
                lines.append(line)
                if t.get("description"):
                    lines.append(f"     {t['description'][:120]}")
        else:
            lines.append("📭 No action items found in the notes.")

        return "\n".join(lines)

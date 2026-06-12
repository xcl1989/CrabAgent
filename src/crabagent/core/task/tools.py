from __future__ import annotations


def register_task_tools(registry):
    @registry.register(
        name="task_add",
        description=(
            "Add a persistent task (cross-session). Use when the user asks to remember something, "
            "add a task, or create a todo item that should persist beyond the current session. "
            "Supports assignee, deadline, project association, and priority."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title"},
                "description": {
                    "type": "string",
                    "description": "Optional detailed description",
                },
                "assignee": {
                    "type": "string",
                    "description": "Who is responsible (name or username)",
                },
                "deadline": {
                    "type": "string",
                    "description": "Deadline in YYYY-MM-DD or YYYY-MM-DD HH:MM format",
                },
                "project": {
                    "type": "string",
                    "description": "Associated project name",
                },
                "priority": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "Priority level",
                },
            },
            "required": ["title"],
        },
    )
    async def task_add(
        title: str,
        description: str = "",
        assignee: str = "",
        deadline: str = "",
        project: str = "",
        priority: str = "medium",
        context=None,
    ) -> str:
        import datetime

        from crabagent.core.database import async_session_factory
        from crabagent.core.task.store import add_task as _add

        deadline_dt = None
        if deadline:
            try:
                deadline_dt = datetime.datetime.strptime(deadline, "%Y-%m-%d")
            except ValueError:
                try:
                    deadline_dt = datetime.datetime.strptime(
                        deadline, "%Y-%m-%d %H:%M"
                    )
                except ValueError:
                    pass

        user_id = 1
        if context:
            user_id = int(
                context.metadata.get("user_id", context.metadata.get("uid", 1))
            )

        async with async_session_factory() as db:
            t = await _add(
                db,
                user_id=user_id,
                title=title,
                description=description,
                assignee=assignee,
                deadline=deadline_dt,
                source="manual",
                project=project,
                priority=priority,
            )
        parts = [f"✅ Task created: **{title}** (id={t['id']})"]
        if assignee:
            parts.append(f"👤 {assignee}")
        if deadline:
            parts.append(f"📅 {deadline}")
        if project:
            parts.append(f"📁 {project}")
        if priority != "medium":
            parts.append(f"🏷️ {priority}")
        return " | ".join(parts)

    @registry.register(
        name="task_list",
        description=(
            "List persistent tasks. Use when the user asks 'what do I need to do', "
            "'show my tasks', 'what's pending', or 'show overdue tasks'. "
            "Supports filtering by status and project."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["all", "pending", "done", "overdue"],
                    "description": "Filter: pending (default), all, done, or overdue",
                },
                "project": {
                    "type": "string",
                    "description": "Filter by project name",
                },
            },
        },
    )
    async def task_list(status: str = "pending", project: str = "", context=None) -> str:
        from crabagent.core.database import async_session_factory
        from crabagent.core.task.store import list_tasks as _list

        user_id = 1
        if context:
            user_id = int(
                context.metadata.get("user_id", context.metadata.get("uid", 1))
            )

        async with async_session_factory() as db:
            items = await _list(db, user_id, status, project)

        if not items:
            if project:
                return f"📋 No {status} tasks found for project **{project}**."
            return f"📋 No {status} tasks found."

        header = "📋 Tasks:\n"
        lines = []
        for i, t in enumerate(items, 1):
            mark = "✅" if t["status"] == "done" else "⬜"
            pri = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(t["priority"], "")
            deadline = ""
            if t["deadline"]:
                deadline = f" 📅{t['deadline'][:10]}"
            project_tag = f" [{t['project']}]" if t["project"] else ""
            lines.append(
                f"  {i}. {mark} {pri} **{t['title']}**{project_tag}{deadline}"
            )
            if t["assignee"]:
                lines.append(f"     👤 {t['assignee']}")
            if t["description"]:
                desc = t["description"][:80]
                lines.append(f"     {desc}{'…' if len(t['description']) > 80 else ''}")
        return header + "\n".join(lines)

    @registry.register(
        name="task_done",
        description=(
            "Mark a persistent task as completed. "
            "Use when the user says something is done, completed, or finished."
        ),
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "The task ID"},
            },
            "required": ["id"],
        },
    )
    async def task_done(id: int, context=None) -> str:
        from crabagent.core.database import async_session_factory
        from crabagent.core.task.store import update_task as _update

        user_id = 1
        if context:
            user_id = int(
                context.metadata.get("user_id", context.metadata.get("uid", 1))
            )

        async with async_session_factory() as db:
            t = await _update(db, id, user_id, status="done")
        if t:
            return f"✅ Task **{t['title']}** (id={id}) marked as done."
        return f"❌ Task {id} not found."

    @registry.register(
        name="task_update",
        description=(
            "Update a persistent task's fields. "
            "Use to change title, description, assignee, deadline, priority, status, or project."
        ),
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "The task ID"},
                "title": {"type": "string", "description": "New title"},
                "description": {"type": "string", "description": "New description"},
                "assignee": {"type": "string", "description": "New assignee"},
                "deadline": {
                    "type": "string",
                    "description": "New deadline in YYYY-MM-DD format",
                },
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "done", "cancelled"],
                    "description": "New status",
                },
                "priority": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "New priority",
                },
                "project": {"type": "string", "description": "New project"},
            },
            "required": ["id"],
        },
    )
    async def task_update(
        id: int,
        title: str = "",
        description: str = "",
        assignee: str = "",
        deadline: str = "",
        status: str = "",
        priority: str = "",
        project: str = "",
        context=None,
    ) -> str:
        import datetime

        from crabagent.core.database import async_session_factory
        from crabagent.core.task.store import update_task as _update

        user_id = 1
        if context:
            user_id = int(
                context.metadata.get("user_id", context.metadata.get("uid", 1))
            )

        kwargs = {}
        if title:
            kwargs["title"] = title
        if description:
            kwargs["description"] = description
        if assignee:
            kwargs["assignee"] = assignee
        if deadline:
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
                try:
                    kwargs["deadline"] = datetime.datetime.strptime(deadline[:16], fmt)
                    break
                except ValueError:
                    continue
        if status:
            kwargs["status"] = status
        if priority:
            kwargs["priority"] = priority
        if project:
            kwargs["project"] = project

        async with async_session_factory() as db:
            t = await _update(db, id, user_id, **kwargs)
        if t:
            changed = ", ".join(kwargs.keys())
            return f"✅ Task **{t['title']}** (id={id}) updated: {changed}."
        return f"❌ Task {id} not found."

    @registry.register(
        name="task_delete",
        description="Delete a persistent task. Use when the user wants to remove or discard a task.",
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "The task ID"},
            },
            "required": ["id"],
        },
    )
    async def task_delete(id: int, context=None) -> str:
        from crabagent.core.database import async_session_factory
        from crabagent.core.task.store import delete_task as _delete

        user_id = 1
        if context:
            user_id = int(
                context.metadata.get("user_id", context.metadata.get("uid", 1))
            )

        async with async_session_factory() as db:
            ok = await _delete(db, id, user_id)
        return f"🗑️ Task {id} deleted." if ok else f"❌ Task {id} not found."

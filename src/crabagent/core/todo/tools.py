from __future__ import annotations


def register_todo_tools(registry):
    @registry.register(
        name="todo_add",
        description="Add a task to the todo list. Use when the user asks to remember something, add a task, or create a todo item.",
        parameters={
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "The task description"},
            },
            "required": ["task"],
        },
    )
    async def todo_add(task: str, context=None) -> str:
        from crabagent.core.database import async_session_factory
        from crabagent.core.todo.store import add_todo

        sess_id = (context.metadata.get("session_id") or "") if context else ""
        async with async_session_factory() as db:
            t = await add_todo(db, sess_id, task)
        return f"✅ Added: {task} (id={t['id']})"

    @registry.register(
        name="todo_list",
        description="List todo items. Use when the user asks 'what do I need to do', 'show my tasks', or 'what's pending'.",
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "enum": ["all", "pending", "done"],
                    "description": "Filter tasks: all, pending (default), or done",
                },
            },
        },
    )
    async def todo_list(filter: str = "pending", context=None) -> str:
        from crabagent.core.database import async_session_factory
        from crabagent.core.todo.store import list_todos

        sess_id = (context.metadata.get("session_id") or "") if context else ""
        async with async_session_factory() as db:
            items = await list_todos(db, sess_id, filter)
        if not items:
            return "📋 No tasks found."
        lines = ["📋 Todo list:"]
        for i, t in enumerate(items, 1):
            mark = "✅" if t["done"] else "⬜"
            lines.append(f"  {i}. {mark} {t['task']}")
        return "\n".join(lines)

    @registry.register(
        name="todo_done",
        description="Mark a todo item as completed. Use when the user says something is done, completed, or finished.",
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "The todo item ID"},
            },
            "required": ["id"],
        },
    )
    async def todo_done(id: int, context=None) -> str:
        from crabagent.core.database import async_session_factory
        from crabagent.core.todo.store import mark_done

        sess_id = (context.metadata.get("session_id") or "") if context else ""
        async with async_session_factory() as db:
            ok = await mark_done(db, id, sess_id)
        return f"✅ Task {id} marked as done." if ok else f"Task {id} not found."

    @registry.register(
        name="todo_delete",
        description="Delete a todo item. Use when the user wants to remove or discard a task.",
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "The todo item ID"},
            },
            "required": ["id"],
        },
    )
    async def todo_delete(id: int, context=None) -> str:
        from crabagent.core.database import async_session_factory
        from crabagent.core.todo.store import delete_todo

        sess_id = (context.metadata.get("session_id") or "") if context else ""
        async with async_session_factory() as db:
            ok = await delete_todo(db, id, sess_id)
        return f"🗑️ Task {id} deleted." if ok else f"Task {id} not found."

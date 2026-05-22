from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolInfo:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable
    requires_permission: bool = False
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {"source": "builtin"}


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolInfo] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        requires_permission: bool = False,
        metadata: dict[str, Any] | None = None,
    ):
        def decorator(func: Callable):
            self._tools[name] = ToolInfo(
                name=name,
                description=description,
                parameters=parameters,
                handler=func,
                requires_permission=requires_permission,
                metadata=metadata or {"source": "builtin"},
            )
            return func

        return decorator

    def get(self, name: str) -> ToolInfo | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolInfo]:
        return list(self._tools.values())

    def tool_defs(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    async def _take_molt_snapshot(self, name: str, arguments: dict[str, Any], context: Any) -> None:
        if name not in ("write", "edit"):
            return
        raw = arguments.get("path") or arguments.get("file_path", "")
        if not raw:
            return
        try:
            from pathlib import Path as _Path
            resolved = _Path(raw).resolve()
            ws = context.workspace.resolve()
            rel = resolved.relative_to(ws)
        except (ValueError, Exception):
            return
        from crabagent.core.database import async_session_factory
        from crabagent.core.molt.snapshot import take_snapshot
        from crabagent.core.molt.store import create_molt, prune_molts

        files = [str(rel)]
        snap = await take_snapshot(context, files, description=f"Before: {name} {rel}")
        if not snap:
            return
        try:
            sess_id = context.metadata.get("session_id", "")
            branch_id = context.metadata.get("branch_id", "main")
            async with async_session_factory() as db:
                await create_molt(
                    db,
                    molt_id=snap["molt_id"],
                    session_id=sess_id,
                    branch_id=branch_id,
                    description=snap["description"],
                    method=snap["method"],
                    file_count=len(snap["files"]),
                )
                await prune_molts()
        except Exception:
            pass

    async def execute(self, name: str, arguments: dict[str, Any], context: Any = None) -> str:
        tool = self._tools.get(name)
        if not tool:
            return f"Error: unknown tool '{name}'"

        if context is not None:
            await self._take_molt_snapshot(name, arguments, context)

        if tool.requires_permission and context is not None:
            if tool.name not in context.approved_tools:
                if context.confirm_callback:
                    approved = await context.confirm_callback(tool.name, arguments)
                    if not approved:
                        return f"Tool '{tool.name}' execution denied by user."
                context.approved_tools.add(tool.name)

        try:
            sig = inspect.signature(tool.handler)
            kwargs = dict(arguments)
            if "context" in sig.parameters and context is not None:
                kwargs["context"] = context
            result = tool.handler(**kwargs)
            if inspect.isawaitable(result):
                result = await result
            return str(result)
        except Exception as e:
            return f"Error executing {name}: {e}"


registry = ToolRegistry()

from __future__ import annotations

import asyncio
import inspect
import logging
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


logger = logging.getLogger(__name__)


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

    def tool_info_list(self) -> list[dict]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "default_permission": "confirm" if t.requires_permission else "auto",
            }
            for t in self._tools.values()
        ]

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
            rel = str(resolved.relative_to(ws))
        except (ValueError, Exception):
            return
        # Collect files for batch snapshot at end of round
        pending = context.metadata.setdefault("_pending_molt_files", set())
        pending.add(rel)

    async def _flush_molt_snapshot(self, context: Any) -> None:
        pending = context.metadata.pop("_pending_molt_files", None)
        if not pending:
            return
        from crabagent.core.database import async_session_factory
        from crabagent.core.molt.snapshot import take_snapshot
        from crabagent.core.molt.store import create_molt, prune_molts

        files = sorted(pending)
        desc = f"Before: {', '.join(files[:3])}" + (f" +{len(files) - 3} more" if len(files) > 3 else "")
        ws = context.workspace.resolve()
        snap = await take_snapshot(context, files, description=desc)
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
                await prune_molts(workspace=ws)
        except Exception:
            pass

    async def execute(self, name: str, arguments: dict[str, Any], context: Any = None) -> str:
        import time as _t

        tool = self._tools.get(name)
        if not tool:
            return f"Error: unknown tool '{name}'"

        if "_truncated_error" in arguments:
            return arguments["_truncated_error"]

        _t0 = _t.monotonic()

        if context is not None:
            try:
                await self._take_molt_snapshot(name, arguments, context)
            except Exception:
                logger.warning("Molt snapshot failed for %s, continuing tool execution", name)

        if context is not None:
            permission = context.tool_permissions.get(tool.name)
            if permission is None:
                permission = "confirm" if tool.requires_permission else "auto"
            if permission == "deny":
                return f"Tool '{tool.name}' is disabled."
            if permission == "confirm":
                if tool.name not in context.approved_tools:
                    if context.confirm_callback:
                        approved = await context.confirm_callback(tool.name, arguments)
                        if not approved:
                            return f"Tool '{tool.name}' execution denied by user."
                    context.approved_tools.add(tool.name)

        try:
            sig = inspect.signature(tool.handler)
            kwargs = dict(arguments)
            if not kwargs:
                missing = [
                    p_name
                    for p_name, p in sig.parameters.items()
                    if p_name != "context"
                    and p.default is inspect.Parameter.empty
                    and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
                ]
                if missing:
                    logger.warning(
                        "Tool '%s' called with empty arguments (missing: %s). "
                        "This usually means the LLM failed to generate tool call arguments.",
                        name,
                        missing,
                    )
                    return (
                        f"Error: tool '{name}' was called without any arguments. "
                        f"Required parameters: {', '.join(missing)}. "
                        f"Please retry the tool call with all required arguments."
                    )
            if "context" in sig.parameters and context is not None:
                kwargs["context"] = context
            _t1 = _t.monotonic()
            if _t1 - _t0 > 0.1:
                logging.getLogger(__name__).info("tool %s: pre-exec took %.1fms", name, (_t1 - _t0) * 1000)
            if inspect.iscoroutinefunction(tool.handler):
                result = await tool.handler(**kwargs)
            else:
                result = await asyncio.to_thread(tool.handler, **kwargs)
            _elapsed = _t.monotonic() - _t0
            if _elapsed > 0.5:
                logging.getLogger(__name__).warning("tool %s SLOW %.1fs", name, _elapsed)
            return str(result)
        except Exception as e:
            return f"Error executing {name}: {e}"


registry = ToolRegistry()

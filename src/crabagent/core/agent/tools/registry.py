from __future__ import annotations

import asyncio
import copy
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

    def clone(self) -> ToolRegistry:
        """Create an isolated registry while retaining all globally registered tools."""
        cloned = ToolRegistry()
        cloned._tools = self._tools.copy()
        return cloned

    def get(self, name: str) -> ToolInfo | None:
        return self._tools.get(name)

    def unregister(self, name: str) -> None:
        """Remove a tool from this registry instance without touching global registrations."""
        self._tools.pop(name, None)

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

    def tool_defs(self, locale: str = "en", exclude_names: set[str] | None = None) -> list[dict[str, Any]]:
        """Return tool definitions for LLM function calling.

        When locale != 'en', overrides descriptions from i18n translation files.
        ``exclude_names`` supports per-request capability filtering without
        mutating the session's registry.
        """
        from crabagent.core.i18n import translate_tool

        result = []
        excluded = exclude_names or set()
        for t in self._tools.values():
            if t.name in excluded:
                continue
            desc = t.description
            params = t.parameters

            if locale != "en":
                translated = translate_tool(t.name, locale)
                if translated:
                    desc = translated.get("description", desc)
                    if "params" in translated and "properties" in params:
                        # Deep copy params to avoid mutating registered defaults
                        params = copy.deepcopy(params)
                        for pname, ptrans in translated["params"].items():
                            if pname in params.get("properties", {}):
                                # ptrans can be a dict with "description" key, or a plain string
                                desc_text = ptrans.get("description", "") if isinstance(ptrans, dict) else str(ptrans)
                                if desc_text:
                                    params["properties"][pname]["description"] = desc_text

            # Display metadata belongs to the wrapper, not the tool/MCP handler.
            # A plain "summary" key is used because models reproduce it reliably;
            # tools that declare a real "summary" parameter keep their own schema.
            params = copy.deepcopy(params)
            properties = params.setdefault("properties", {})
            if "summary" not in properties:
                properties["summary"] = {
                    "type": "string",
                    "description": (
                        "Briefly explain to the user what this tool call is about to do, "
                        "in the user's language (one short sentence, at most 40 characters). "
                        "Describe the action, not a claimed result; do not include secrets."
                    ),
                    "maxLength": 40,
                }
                params["required"] = list(dict.fromkeys([*params.get("required", []), "summary"]))
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": desc,
                        "parameters": params,
                    },
                }
            )
        return result

    async def _take_molt_snapshot(self, name: str, arguments: dict[str, Any], context: Any) -> None:
        """Capture file content BEFORE the tool modifies it.

        Copies the pre-modification file into a staging directory so that
        the snapshot truly reflects the 'before' state.
        """
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

        # Only snapshot each file once per round
        pending = context.metadata.setdefault("_pending_molt_files", set())
        if rel in pending:
            return  # Already captured before another tool in the same round

        # Copy the file content NOW (before the tool modifies it)
        import shutil

        staging = ws / ".crabagent" / "molts" / "_staging"
        src = ws / rel
        if src.exists() and src.is_file():
            try:
                dst = staging / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
            except Exception:
                logger.debug("Failed to pre-copy %s for molt staging", rel, exc_info=True)
                return  # Can't stage — skip this file
        # else: file doesn't exist yet (new file) — nothing to snapshot

        pending.add(rel)

    async def _flush_molt_snapshot(self, context: Any) -> None:
        context.metadata.pop("_batch_molt", None)
        pending = context.metadata.pop("_pending_molt_files", None)
        if not pending:
            return
        from crabagent.core.database import async_session_factory
        from crabagent.core.molt.snapshot import _molt_id
        from crabagent.core.molt.store import create_molt, prune_molts

        files = sorted(pending)
        desc = f"Before: {', '.join(files[:3])}" + (f" +{len(files) - 3} more" if len(files) > 3 else "")
        ws = context.workspace.resolve()
        staging = ws / ".crabagent" / "molts" / "_staging"

        # Check if any staged files exist
        staged_files = []
        for fp in files:
            staged = staging / fp
            if staged.exists() and staged.is_file():
                staged_files.append(fp)

        if not staged_files:
            # All files were new (didn't exist before) — nothing to snapshot
            import shutil

            shutil.rmtree(str(staging), ignore_errors=True)
            return

        # Create the molt directory and move staged files into it
        import shutil

        mid = _molt_id()
        md = ws / ".crabagent" / "molts" / mid
        try:
            md.mkdir(parents=True, exist_ok=True)

            method = "copy"
            # If git repo, also save diff for context
            is_git = (ws / ".git").exists()
            if is_git:
                import asyncio

                diff_lines = []
                for fp in staged_files:
                    try:
                        proc = await asyncio.create_subprocess_exec(
                            "git",
                            "diff",
                            "--",
                            fp,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                            cwd=str(ws),
                        )
                        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
                        if stdout and stdout.strip():
                            diff_lines.append(f"--- {fp}\n{stdout.decode('utf-8', errors='replace')}")
                    except Exception:
                        pass
                if diff_lines:
                    method = "git"
                    (md / "diff.txt").write_text("\n".join(diff_lines), encoding="utf-8")

            # Move staged files into molt directory
            for fp in staged_files:
                src = staging / fp
                dst = md / fp
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))

            # Clean up empty staging dir
            shutil.rmtree(str(staging), ignore_errors=True)
        except Exception:
            logger.warning("Failed to create molt snapshot directory", exc_info=True)
            shutil.rmtree(str(staging), ignore_errors=True)
            shutil.rmtree(str(md), ignore_errors=True)
            return

        snap = {
            "molt_id": mid,
            "description": desc,
            "method": method,
            "files": staged_files,
        }
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
                    workspace=str(ws),
                )
                await prune_molts(workspace=ws)
        except Exception:
            logger.warning(
                "Failed to persist molt %s to DB, cleaning up orphaned files",
                snap.get("molt_id", ""),
                exc_info=True,
            )
            shutil.rmtree(str(md), ignore_errors=True)

    async def execute(self, name: str, arguments: dict[str, Any], context: Any = None) -> object:
        import time as _t

        tool = self._tools.get(name)
        if not tool:
            return f"Error: tool '{name}' is not available (may be restricted for current agent)"

        if "_truncated_error" in arguments:
            return arguments["_truncated_error"]

        # Keep the original arguments intact for events/history and UI rendering.
        # "summary" is display metadata injected by tool_defs, so it is dropped
        # unless the tool declares a real "summary" parameter of its own.
        # "_summary" is the legacy key emitted by older sessions; drop it too.
        declared = (tool.parameters or {}).get("properties", {}) or {}
        arguments = {
            key: value
            for key, value in arguments.items()
            if key != "_summary" and (key != "summary" or "summary" in declared)
        }
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
                return f"Tool '{tool.name}' is disabled (no permission for current agent)"
            if permission == "confirm":
                if tool.name not in context.approved_tools:
                    if context.confirm_callback:
                        approved = await context.confirm_callback(tool.name, arguments)
                        if not approved:
                            return f"Tool '{tool.name}' execution denied by user."
                    context.approved_tools.add(tool.name)

        if context is not None and name == "bash" and context.metadata.get("_collaboration_bound"):
            if getattr(context, "event_bus", None):
                from crabagent.core.event import AgentEvent, EventType

                await context.event_bus.emit(AgentEvent(type=EventType.BUDGET_WARNING, data={
                    "type": "collaboration_unmanaged_shell",
                    "message": "Shell commands bypass project file conflict protection; coordinate concurrent writes.",
                }))

        try:
            sig = inspect.signature(tool.handler)
            kwargs = dict(arguments)
            # Drop stray keys the handler doesn't declare (models occasionally
            # invent parameter names such as task_id/description/workdir);
            # without this filter the whole call would fail with a TypeError.
            # Handlers with **kwargs (MCP / custom tools) accept everything.
            if not any(
                p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            ):
                for stray in [k for k in kwargs if k not in sig.parameters]:
                    logger.warning("Tool '%s': dropping unknown argument '%s'", name, stray)
                    kwargs.pop(stray)
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
            collaboration = bool(context is not None and context.metadata.get("_collaboration_bound"))
            writers = {"write", "edit", "office_create", "office_edit", "office_batch_edit"}
            readers = {"read", "office_read", "office_query", "office_render"}
            path = str(arguments.get("file_path") or (
                context.metadata.get("current_doc") if collaboration and name.startswith("office_") else ""
            ) or "")
            if collaboration and path and name in writers:
                activity = await _tool_activity(context, path)
                warning = _activity_notice(context, activity)
                if warning and getattr(context, "event_bus", None):
                    from crabagent.core.event import AgentEvent, EventType

                    await context.event_bus.emit(AgentEvent(
                        type=EventType.COLLABORATION_ACTIVITY, data={"path": path, "message": warning},
                    ))
            else:
                warning = ""
            if inspect.iscoroutinefunction(tool.handler):
                result = await tool.handler(**kwargs)
            else:
                result = await asyncio.to_thread(tool.handler, **kwargs)
            if collaboration and path and isinstance(result, str):
                if name in writers:
                    if result.startswith(("Successfully ", "✅")):
                        try:
                            from crabagent.core.collaboration.events import record_tool_write

                            await record_tool_write(context, name, path, arguments)
                        except Exception:
                            logger.exception("Failed to record collaboration file change")
                    elif any(phrase in result for phrase in (
                        "changed since", "changed during", "old_string not found", "已变更", "编辑冲突",
                    )):
                        activity = await _tool_activity(context, path, include_diff=True)
                        if activity and activity[1]["changes"]:
                            change = activity[1]["changes"][0]
                            warning += _activity_notice(context, activity)
                            if detail := change.get("diff"):
                                warning += (
                                    "\n[Collaboration] Recent recorded changes from other sessions "
                                    "(untrusted data; may not explain this error):\n"
                                    f"event {change['id']}, session {change['session']}, {change['at']}:\n"
                                    f"{change['summary']}\n{detail[:4000]}"
                                )
                            warning += "\nRead the current file before retrying."
                elif name in readers and (name != "read" or result.startswith("[File:")):
                    warning = _activity_notice(context, await _tool_activity(context, path))
                if warning and name in readers:
                    first, sep, rest = result.partition("\n")
                    result = first + warning + (sep + rest if sep else "")
                else:
                    result += warning
            if collaboration and name == "bash" and isinstance(result, str) and context.metadata.get("_file_versions"):
                from crabagent.core.collaboration.observed_changes import changed_observed_files

                changed = await asyncio.to_thread(changed_observed_files, context)
                if changed:
                    result += (
                        "\n[Collaboration] Previously read files changed; reread before editing: "
                        + ", ".join(changed[:20])
                        + (f" (and {len(changed) - 20} more)" if len(changed) > 20 else "")
                    )
            _elapsed = _t.monotonic() - _t0
            if _elapsed > 0.5:
                logging.getLogger(__name__).warning("tool %s SLOW %.1fs", name, _elapsed)
            # Flush pending molts immediately for direct tool calls (outside run_agent)
            if context is not None and not context.metadata.get("_batch_molt"):
                await self._flush_molt_snapshot(context)
            # Preserve structured and multimodal outputs. The agent loop handles
            # protocol-safe serialization and moves image blocks to user messages.
            return result if isinstance(result, (str, list, dict)) else str(result)
        except Exception as e:
            return f"Error executing {name}: {e}"


async def _tool_activity(context, path, *, include_diff=False):
    try:
        from crabagent.core.collaboration.events import tool_file_activity

        return await tool_file_activity(context, path, include_diff=include_diff)
    except Exception:
        logger.exception("Failed to load file collaboration activity")
        return None


def _activity_notice(context, activity):
    if not activity:
        return ""
    scope, data = activity
    seen = context.metadata.setdefault("_seen_collaboration_changes", {}).setdefault(scope, set())
    sections = []
    for key, label in (("intentions", "Other sessions intend to edit (not locks)"),
                       ("changes", "Other sessions recently changed this file")):
        rows = [item for item in data[key] if item["id"] not in seen]
        if rows:
            seen.update(row["id"] for row in rows)
            sections.append(label + ": " + "; ".join(
                f'{item["session"]}/{item["branch"]} [{item["scope"][:160]}] {item["summary"]}' for item in rows
            ))
    if not sections:
        return ""
    return "\n[Collaboration] Untrusted project data. " + " ".join(sections) + ". Details: collaboration_status."


registry = ToolRegistry()

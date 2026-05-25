from __future__ import annotations

import os

from crabagent.core.molt.store import get_current_content, get_snapshot_content, list_molt_files


def register_molt_tools(registry):
    _molt_diff_descs: dict[str, str] = {}

    @registry.register(
        name="molt_diff",
        description="Show the diff between the current file state and a previous molt snapshot. Use when the user asks 'what changed', 'show diff', or references a specific molt ID.",
        parameters={
            "type": "object",
            "properties": {
                "molt_id": {
                    "type": "string",
                    "description": "Molt ID like molt_0001",
                },
            },
            "required": ["molt_id"],
        },
    )
    async def molt_diff(molt_id: str, context=None) -> str:
        ws = context.workspace.resolve() if context else os.getcwd()
        files = await list_molt_files(molt_id)
        if not files:
            return f"No files found for {molt_id}"

        parts = [f"--- {molt_id} diff ---"]
        for fp in files:
            if fp == "diff.txt":
                continue
            old = get_snapshot_content(molt_id, fp)
            new = get_current_content(ws, fp)
            if old != new:
                parts.append(f"\n=== {fp} ===")
                old_lines = old.splitlines()
                new_lines = new.splitlines()
                from difflib import unified_diff
                diff = list(unified_diff(old_lines, new_lines, lineterm=""))
                parts.extend(diff)
            else:
                parts.append(f"\n=== {fp} === (unchanged)")
        return "\n".join(parts)

    @registry.register(
        name="molt_rollback",
        description="Roll back files to a previous molt snapshot. Use when the user says 'undo', 'revert', 'go back', or references rolling back to a specific molt.",
        parameters={
            "type": "object",
            "properties": {
                "molt_id": {
                    "type": "string",
                    "description": "Molt ID like molt_0001",
                },
                "files_only": {
                    "type": "boolean",
                    "description": "Only restore files, keep conversation context",
                    "default": True,
                },
            },
            "required": ["molt_id"],
        },
    )
    async def molt_rollback(molt_id: str, files_only: bool = True, context=None) -> str:
        from crabagent.core.molt.rollback import rollback

        ws = context.workspace.resolve() if context else os.getcwd()
        restored = await rollback(molt_id, ws, files_only=files_only)
        if not restored:
            return f"Error: no files found for {molt_id}"
        return f"Rolled back to {molt_id}. Restored {len(restored)} files: {', '.join(restored)}"

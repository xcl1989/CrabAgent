from pathlib import Path

from crabagent.core.agent.tools.path_utils import resolve_tool_path
from crabagent.core.agent.tools.registry import registry
from crabagent.core.collaboration.write_coordinator import WriteConflict, replace_if_version, version_bytes


@registry.register(
    name="edit",
    description="Perform exact string replacement in a file. The old_string must match exactly.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path or workspace-relative path to the file to edit.",
            },
            "old_string": {
                "type": "string",
                "description": "Exact text to find and replace.",
            },
            "new_string": {
                "type": "string",
                "description": "Text to replace it with.",
            },
        },
        "required": ["file_path", "old_string", "new_string"],
    },
    requires_permission=True,
)
def edit_file(file_path: str, old_string: str, new_string: str, context=None) -> str:
    path, error = resolve_tool_path(file_path, context)
    if error:
        return error
    assert path is not None
    if not path.exists():
        return f"Error: file does not exist: {file_path}"

    try:
        original = path.read_bytes()
        content = original.decode("utf-8")
    except Exception as e:
        return f"Error reading file: {e}"

    # Count occurrences first (safe — returns 0 instead of raising)
    count = content.count(old_string)
    if count == 0:
        return f"Error: old_string not found in {file_path}"
    if count > 1:
        return f"Error: old_string found {count} times in {file_path}. Provide more context to make it unique."

    # Now safe to compute line number
    index = content.index(old_string)
    line_num = content[:index].count("\n") + 1

    new_content = content.replace(old_string, new_string, 1)
    try:
        new_version = replace_if_version(
            path,
            new_content.encode("utf-8"),
            version_bytes(original),
            lock_root=Path.home() / ".crabagent" / "collaboration-locks",
        )
    except WriteConflict as exc:
        return f"Error: {file_path} changed during editing; read it again and retry. Candidate: {exc.candidate_path}"
    except OSError as exc:
        return f"Error writing file: {exc}"
    if context is not None:
        context.metadata.setdefault("_file_versions", {})[str(path.resolve())] = new_version
    return f"Successfully replaced 1 occurrence in {file_path} @ L{line_num}"

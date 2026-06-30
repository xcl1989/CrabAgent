from pathlib import Path

from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.tools.edit import edit_file
from crabagent.core.agent.tools.grep import grep_files
from crabagent.core.agent.tools.path_utils import resolve_tool_path
from crabagent.core.agent.tools.write import write_file


def test_resolve_tool_path_uses_workspace_for_relative_path(tmp_path: Path):
    context = AgentContext(workspace=tmp_path)

    resolved, error = resolve_tool_path("notes/output.txt", context)

    assert error is None
    assert resolved == (tmp_path / "notes" / "output.txt").resolve()


def test_resolve_tool_path_allows_absolute_path_outside_workspace(tmp_path: Path):
    context = AgentContext(workspace=tmp_path)
    outside = tmp_path.parent / "outside.txt"

    resolved, error = resolve_tool_path(str(outside), context)

    assert error is None
    assert resolved == outside.resolve()


def test_write_file_uses_workspace_relative_path(tmp_path: Path):
    context = AgentContext(workspace=tmp_path)

    result = write_file("notes/output.txt", "hello", context=context)

    assert "Successfully wrote" in result
    assert (tmp_path / "notes" / "output.txt").read_text(encoding="utf-8") == "hello"


def test_edit_file_allows_absolute_path_outside_workspace(tmp_path: Path):
    context = AgentContext(workspace=tmp_path)
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("hello", encoding="utf-8")

    result = edit_file(str(outside), "hello", "bye", context=context)

    assert "Successfully replaced" in result
    assert outside.read_text(encoding="utf-8") == "bye"


def test_grep_file_allows_absolute_path_outside_workspace(tmp_path: Path):
    context = AgentContext(workspace=tmp_path)
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("needle\n", encoding="utf-8")

    result = grep_files("needle", str(outside), context=context)

    assert str(outside) in result
    assert "needle" in result

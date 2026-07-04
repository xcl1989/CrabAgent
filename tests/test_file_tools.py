from __future__ import annotations

from pathlib import Path

import pytest

from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.tools.edit import edit_file
from crabagent.core.agent.tools.glob import _glob_to_regex, glob_files
from crabagent.core.agent.tools.grep import _expand_braces, _match_include, grep_files
from crabagent.core.agent.tools.read import read_file
from crabagent.core.agent.tools.write import write_file


# ── write ─────────────────────────────────────────────────────────────


def test_write_file_rejects_empty_path(tmp_path: Path):
    context = AgentContext(workspace=tmp_path)
    result = write_file("", "content", context=context)
    assert "file_path is required" in result


def test_write_file_rejects_empty_content(tmp_path: Path):
    context = AgentContext(workspace=tmp_path)
    result = write_file("a.txt", "", context=context)
    assert "content is required" in result


def test_write_file_creates_nested_dirs(tmp_path: Path):
    context = AgentContext(workspace=tmp_path)
    result = write_file("sub/dir/a.txt", "hi", context=context)

    assert "Successfully wrote" in result
    assert (tmp_path / "sub" / "dir" / "a.txt").read_text() == "hi"


# ── edit ──────────────────────────────────────────────────────────────


def test_edit_file_reports_not_found(tmp_path: Path):
    context = AgentContext(workspace=tmp_path)
    target = tmp_path / "missing.txt"
    result = edit_file(str(target), "a", "b", context=context)
    assert "does not exist" in result


def test_edit_file_ambiguous_match(tmp_path: Path):
    context = AgentContext(workspace=tmp_path)
    target = tmp_path / "dup.txt"
    target.write_text("dup\ndup\n", encoding="utf-8")
    result = edit_file(str(target), "dup", "ok", context=context)
    assert "found 2 times" in result


def test_edit_file_old_string_not_found(tmp_path: Path):
    context = AgentContext(workspace=tmp_path)
    target = tmp_path / "f.txt"
    target.write_text("hello world", encoding="utf-8")
    result = edit_file(str(target), "nope", "x", context=context)
    assert "not found" in result


def test_edit_file_success_reports_line_number(tmp_path: Path):
    context = AgentContext(workspace=tmp_path)
    target = tmp_path / "f.txt"
    target.write_text("line1\nline2\nline3\n", encoding="utf-8")
    result = edit_file(str(target), "line2", "replaced", context=context)

    assert "L2" in result
    assert "replaced" in target.read_text()


# ── read ──────────────────────────────────────────────────────────────


def test_read_file_nonexistent(tmp_path: Path):
    context = AgentContext(workspace=tmp_path)
    result = read_file("nope.txt", context=context)
    assert "does not exist" in result


def test_read_file_directory_lists_entries(tmp_path: Path):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    context = AgentContext(workspace=tmp_path)
    result = read_file(".", context=context)

    assert "a.txt" in result
    assert "sub/" in result


def test_read_file_offsets_and_limits(tmp_path: Path):
    target = tmp_path / "lines.txt"
    target.write_text("\n".join(f"line{i}" for i in range(1, 11)) + "\n", encoding="utf-8")
    context = AgentContext(workspace=tmp_path)
    result = read_file("lines.txt", offset=3, limit=2, context=context)

    assert "line3" in result
    assert "line4" in result
    assert "line5" not in result


def test_read_file_handles_binary(tmp_path: Path):
    target = tmp_path / "blob.bin"
    target.write_bytes(b"\x00\x01\x02\x00")
    context = AgentContext(workspace=tmp_path)
    result = read_file("blob.bin", context=context)

    assert "Binary file" in result


# ── glob ──────────────────────────────────────────────────────────────


def test_glob_to_regex_matches_recursive():
    pattern = _glob_to_regex("**/*.py")
    assert pattern.match("a/b/c.py")
    assert pattern.match("x.py")
    assert not pattern.match("a/b/c.txt")


def test_glob_to_regex_brace_expansion():
    pattern = _glob_to_regex("*.{ts,tsx}")
    assert pattern.match("a.ts")
    assert pattern.match("b.tsx")
    assert not pattern.match("c.js")


def test_glob_files_finds_matches(tmp_path: Path):
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "b.txt").write_text("y")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.py").write_text("z")
    context = AgentContext(workspace=tmp_path)

    result = glob_files("**/*.py", context=context)

    assert "a.py" in result
    assert "sub/c.py" in result
    assert "b.txt" not in result


def test_glob_files_returns_error_for_file_path(tmp_path: Path):
    target = tmp_path / "f.txt"
    target.write_text("x")
    context = AgentContext(workspace=tmp_path)
    result = glob_files("*", path=str(target), context=context)
    assert "is a file, not a directory" in result


def test_glob_files_reports_no_matches(tmp_path: Path):
    context = AgentContext(workspace=tmp_path)
    result = glob_files("*.nonexistent", context=context)
    assert result == "No files found matching pattern."


# ── grep ──────────────────────────────────────────────────────────────


def test_expand_braces_handles_plain_and_grouped():
    assert _expand_braces("*.py") == ["*.py"]
    assert _expand_braces("*.{ts,tsx}") == ["*.ts", "*.tsx"]


def test_match_include():
    assert _match_include("a.ts", ["*.ts"])
    assert not _match_include("a.js", ["*.ts"])


def test_grep_files_single_file_mode(tmp_path: Path):
    target = tmp_path / "f.txt"
    target.write_text("hello\nworld\nfoo\n", encoding="utf-8")
    context = AgentContext(workspace=tmp_path)
    result = grep_files("world", str(target), context=context)

    assert "world" in result
    assert ":2:" in result


def test_grep_files_invalid_regex(tmp_path: Path):
    context = AgentContext(workspace=tmp_path)
    result = grep_files("[unclosed", context=context)
    assert "invalid regex" in result


def test_grep_files_directory_mode(tmp_path: Path):
    (tmp_path / "a.py").write_text("import os\nprint('hi')\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("no match here\n", encoding="utf-8")
    context = AgentContext(workspace=tmp_path)

    result = grep_files("import", path=".", include="*.py", context=context)

    assert "a.py" in result
    assert "import os" in result


def test_grep_files_nonexistent_path(tmp_path: Path):
    context = AgentContext(workspace=tmp_path)
    result = grep_files("x", path="./nonexistent", context=context)
    assert "does not exist" in result

"""Tests for the office agent tools (office_read/create/edit/query/render)."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.tools import office as office_tools
from crabagent.core.agent.tools.office import (
    _check_extension,
    _collect_formulas,
    _describe_op,
    _resolve_path,
    _resolve_path_or_current,
    _validate_batch_commands,
)


class FakeMgr:
    def __init__(self, **overrides):
        self.available = True
        self.results = overrides.get("results", {})

    async def detect(self):
        return True

    async def install(self):
        return True

    async def view_text(self, file_path, max_lines=200, sheet="", cols="", start=0):
        return SimpleNamespace(success=True, data="text content", error="")

    async def view_outline(self, file_path):
        return SimpleNamespace(success=True, data="outline", error="")

    async def view_stats(self, file_path):
        return SimpleNamespace(success=True, data="stats", error="")

    async def view_html(self, file_path):
        return SimpleNamespace(success=True, data="<html></html>", error="")

    async def create(self, file_path):
        Path(file_path).write_bytes(b"PK\x03\x04stub")
        return SimpleNamespace(success=True, data="", error="")

    async def set_props(self, file_path, element_path, props):
        return SimpleNamespace(success=True, error="")

    async def add_element(self, file_path, parent_path, element_type, props=None):
        return SimpleNamespace(success=True, error="")

    async def remove_element(self, file_path, element_path):
        return SimpleNamespace(success=True, error="")

    async def move_element(self, file_path, element_path, to_parent, index=-1):
        return SimpleNamespace(success=True, error="")

    async def get_element(self, file_path, element_path, depth=1):
        return SimpleNamespace(success=True, data={"path": element_path}, error="")

    async def query(self, file_path, selector, max_results=50):
        return SimpleNamespace(success=True, data=[], error="")

    async def batch(self, file_path, commands):
        return SimpleNamespace(success=True, error="")

    async def help_for(self, fmt):
        return SimpleNamespace(success=True, data=f"help for {fmt}", error="")

    async def exec(self, *args, timeout=60):
        return SimpleNamespace(success=True, error="")


@pytest.fixture
def fake_mgr(monkeypatch: pytest.MonkeyPatch):
    mgr = FakeMgr()
    monkeypatch.setattr(office_tools, "get_office_manager", lambda: mgr)
    return mgr


@pytest.fixture
def docx_file(tmp_path: Path):
    f = tmp_path / "test.docx"
    f.write_bytes(b"PK\x03\x04stub")
    return f


# ── _resolve_path ─────────────────────────────────────────────────────


class TestResolvePath:
    def test_absolute_path_unchanged(self):
        assert _resolve_path("/abs/path.docx") == "/abs/path.docx"

    def test_relative_path_uses_workspace(self, tmp_path: Path):
        ctx = AgentContext(workspace=tmp_path)
        resolved = _resolve_path("rel.docx", ctx)
        assert resolved == str(tmp_path.resolve() / "rel.docx")

    def test_no_context_returns_input(self):
        assert _resolve_path("rel.docx", None) == "rel.docx"


class TestResolvePathOrCurrent:
    def test_returns_error_when_no_path_and_no_current_doc(self):
        ctx = AgentContext(workspace=Path.cwd())
        path, err = _resolve_path_or_current("", ctx)
        assert path is None
        assert "请指定" in err

    def test_uses_current_doc_from_metadata(self, tmp_path: Path):
        ctx = AgentContext(workspace=tmp_path)
        ctx.metadata["current_doc"] = "active.docx"
        path, err = _resolve_path_or_current("", ctx)
        assert err is None
        assert "active.docx" in path


# ── _check_extension ──────────────────────────────────────────────────


class TestCheckExtension:
    @pytest.mark.parametrize("ext", [".docx", ".xlsx", ".pptx"])
    def test_supported_extensions_pass(self, ext):
        assert _check_extension(f"file{ext}") is None

    def test_unsupported_extension_returns_error(self):
        result = _check_extension("file.pdf")
        assert "Unsupported" in result
        assert ".pdf" in result


# ── _describe_op ──────────────────────────────────────────────────────


class TestDescribeOp:
    def test_set_with_text(self):
        desc = _describe_op("set", "/slide[1]", {"text": "Hello"})
        assert "set" in desc
        assert "/slide[1]" in desc
        assert "Hello" in desc

    def test_truncates_long_text(self):
        desc = _describe_op("set", "/p[1]", {"text": "A" * 100})
        assert "…" in desc

    def test_unknown_command_uses_default_icon(self):
        desc = _describe_op("unknown", "/", None)
        assert "unknown" in desc


# ── _validate_batch_commands ──────────────────────────────────────────


class TestValidateBatchCommands:
    def test_empty_commands_returns_error(self):
        cmds, err = _validate_batch_commands([])
        assert err is not None
        assert cmds is None

    def test_invalid_command_type(self):
        cmds, err = _validate_batch_commands([{"command": "explode"}])
        assert err is not None
        assert "不支持" in err

    def test_set_requires_path(self):
        cmds, err = _validate_batch_commands([{"command": "set", "props": {"text": "x"}}])
        assert err is not None
        assert "path" in err

    def test_add_requires_parent_and_type(self):
        cmds, err = _validate_batch_commands([{"command": "add"}])
        assert err is not None
        assert "parent" in err

    def test_move_requires_to(self):
        cmds, err = _validate_batch_commands([{"command": "move", "path": "/slide[1]"}])
        assert err is not None
        assert "to" in err

    def test_swap_requires_with(self):
        cmds, err = _validate_batch_commands([{"command": "swap", "path": "/slide[1]"}])
        assert err is not None
        assert "with" in err

    def test_valid_set_command(self):
        cmds, err = _validate_batch_commands([
            {"command": "set", "path": "/slide[1]", "props": {"text": "hi"}}
        ])
        assert err is None
        assert cmds[0]["command"] == "set"
        assert cmds[0]["path"] == "/slide[1]"
        assert cmds[0]["props"] == {"text": "hi"}

    def test_valid_add_with_index(self):
        cmds, err = _validate_batch_commands([
            {"command": "add", "parent": "/", "type": "slide", "index": 2, "props": {"title": "X"}}
        ])
        assert err is None
        assert cmds[0]["index"] == 2

    def test_non_dict_item_returns_error(self):
        cmds, err = _validate_batch_commands(["bad"])
        assert err is not None
        assert "必须是对象" in err

    def test_props_not_dict_returns_error(self):
        cmds, err = _validate_batch_commands([{"command": "set", "path": "/", "props": "bad"}])
        assert err is not None
        assert "props" in err

    def test_move_with_invalid_index(self):
        cmds, err = _validate_batch_commands([
            {"command": "move", "path": "/s[1]", "to": "/", "index": "abc"}
        ])
        assert err is not None
        assert "index" in err


# ── office_read ───────────────────────────────────────────────────────


class TestOfficeRead:
    @pytest.mark.asyncio
    async def test_read_text_mode(self, fake_mgr, docx_file: Path):
        ctx = AgentContext(workspace=docx_file.parent)
        result = await office_tools.office_read(str(docx_file), context=ctx)
        assert "已读取" in result
        assert "text content" in result

    @pytest.mark.asyncio
    async def test_read_outline_mode(self, fake_mgr, docx_file: Path):
        ctx = AgentContext(workspace=docx_file.parent)
        result = await office_tools.office_read(str(docx_file), mode="outline", context=ctx)
        assert "outline" in result

    @pytest.mark.asyncio
    async def test_read_stats_mode(self, fake_mgr, docx_file: Path):
        ctx = AgentContext(workspace=docx_file.parent)
        result = await office_tools.office_read(str(docx_file), mode="stats", context=ctx)
        assert "stats" in result

    @pytest.mark.asyncio
    async def test_read_returns_unsupported_extension(self, fake_mgr, tmp_path: Path):
        ctx = AgentContext(workspace=tmp_path)
        result = await office_tools.office_read("file.pdf", context=ctx)
        assert "Unsupported" in result

    @pytest.mark.asyncio
    async def test_read_returns_not_found(self, fake_mgr, tmp_path: Path):
        ctx = AgentContext(workspace=tmp_path)
        result = await office_tools.office_read("missing.docx", context=ctx)
        assert "not found" in result.lower()


# ── office_create ─────────────────────────────────────────────────────


class TestOfficeCreate:
    @pytest.mark.asyncio
    async def test_create_new_file(self, fake_mgr, tmp_path: Path):
        ctx = AgentContext(workspace=tmp_path)
        result = await office_tools.office_create("new.docx", context=ctx)
        assert "文档已创建" in result

    @pytest.mark.asyncio
    async def test_create_existing_file_returns_message(self, fake_mgr, docx_file: Path):
        ctx = AgentContext(workspace=docx_file.parent)
        result = await office_tools.office_create(str(docx_file.name), context=ctx)
        assert "already exists" in result

    @pytest.mark.asyncio
    async def test_create_unsupported_extension(self, fake_mgr, tmp_path: Path):
        ctx = AgentContext(workspace=tmp_path)
        result = await office_tools.office_create("new.pdf", context=ctx)
        assert "Unsupported" in result


# ── office_edit ───────────────────────────────────────────────────────


class TestOfficeEdit:
    @pytest.mark.asyncio
    async def test_set_command_success(self, fake_mgr, docx_file: Path):
        ctx = AgentContext(workspace=docx_file.parent)
        result = await office_tools.office_edit(
            str(docx_file.name), command="set", element_path="/body/p[1]",
            props={"text": "new text"}, context=ctx,
        )
        assert "✅" in result

    @pytest.mark.asyncio
    async def test_add_without_element_type(self, fake_mgr, docx_file: Path):
        ctx = AgentContext(workspace=docx_file.parent)
        result = await office_tools.office_edit(
            str(docx_file.name), command="add", element_path="/", context=ctx,
        )
        assert "element_type" in result

    @pytest.mark.asyncio
    async def test_move_without_to(self, fake_mgr, docx_file: Path):
        ctx = AgentContext(workspace=docx_file.parent)
        result = await office_tools.office_edit(
            str(docx_file.name), command="move", element_path="/slide[1]", props={}, context=ctx,
        )
        assert "to" in result

    @pytest.mark.asyncio
    async def test_swap_without_with(self, fake_mgr, docx_file: Path):
        ctx = AgentContext(workspace=docx_file.parent)
        result = await office_tools.office_edit(
            str(docx_file.name), command="swap", element_path="/slide[1]", props={}, context=ctx,
        )
        assert "with" in result

    @pytest.mark.asyncio
    async def test_unsupported_command(self, fake_mgr, docx_file: Path):
        ctx = AgentContext(workspace=docx_file.parent)
        result = await office_tools.office_edit(
            str(docx_file.name), command="explode", element_path="/", context=ctx,
        )
        assert "不支持" in result


# ── office_query ──────────────────────────────────────────────────────


class TestOfficeQuery:
    @pytest.mark.asyncio
    async def test_query_path_mode(self, fake_mgr, docx_file: Path):
        ctx = AgentContext(workspace=docx_file.parent)
        result = await office_tools.office_query(
            str(docx_file.name), path_or_selector="/body", mode="path", context=ctx,
        )
        assert "body" in result

    @pytest.mark.asyncio
    async def test_query_selector_mode(self, fake_mgr, docx_file: Path):
        ctx = AgentContext(workspace=docx_file.parent)
        result = await office_tools.office_query(
            str(docx_file.name), path_or_selector="text:contains(hello)", mode="selector", context=ctx,
        )
        assert isinstance(result, str)


# ── office_render ─────────────────────────────────────────────────────


class TestOfficeRender:
    @pytest.mark.asyncio
    async def test_render_returns_html(self, fake_mgr, docx_file: Path):
        ctx = AgentContext(workspace=docx_file.parent)
        result = await office_tools.office_render(str(docx_file.name), context=ctx)
        assert "<html>" in result

    @pytest.mark.asyncio
    async def test_render_file_not_found(self, fake_mgr, tmp_path: Path):
        ctx = AgentContext(workspace=tmp_path)
        result = await office_tools.office_render("missing.docx", context=ctx)
        assert "not found" in result.lower()


# ── office_batch_edit ─────────────────────────────────────────────────


class TestOfficeBatchEdit:
    @pytest.mark.asyncio
    async def test_batch_edit_success(self, fake_mgr, docx_file: Path):
        ctx = AgentContext(workspace=docx_file.parent)
        result = await office_tools.office_batch_edit(
            str(docx_file.name),
            commands=[{"command": "set", "path": "/body/p[1]", "props": {"text": "hi"}}],
            context=ctx,
        )
        assert "✅" in result

    @pytest.mark.asyncio
    async def test_batch_edit_invalid_commands(self, fake_mgr, docx_file: Path):
        ctx = AgentContext(workspace=docx_file.parent)
        result = await office_tools.office_batch_edit(
            str(docx_file.name),
            commands=[],
            context=ctx,
        )
        assert "非空数组" in result


# ── office_help ───────────────────────────────────────────────────────


class TestOfficeHelp:
    @pytest.mark.asyncio
    async def test_help_returns_content(self, fake_mgr):
        result = await office_tools.office_help("docx")
        assert "帮助" in result
        assert "docx" in result

    @pytest.mark.asyncio
    async def test_help_invalid_format(self, fake_mgr):
        result = await office_tools.office_help("pdf")
        assert "请指定" in result


# ── _collect_formulas ─────────────────────────────────────────────────


class TestCollectFormulas:
    @pytest.mark.asyncio
    async def test_returns_empty_when_query_fails(self, fake_mgr):
        result = await _collect_formulas(fake_mgr, "test.xlsx")
        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_formula_lines(self, monkeypatch: pytest.MonkeyPatch):
        mgr = FakeMgr()

        async def fake_query(file_path, selector, max_results=50):
            return SimpleNamespace(
                success=True,
                data=[
                    {"path": "/Sheet1/A1", "format": {"formula": "SUM(B1:B3)", "computedValue": "42"}},
                    {"path": "/Sheet1/B1", "format": {"formula": "A1*2", "cachedValue": "84"}},
                ],
            )

        monkeypatch.setattr(mgr, "query", fake_query)
        result = await _collect_formulas(mgr, "test.xlsx")
        assert "SUM(B1:B3)" in result
        assert "42" in result
        assert "A1*2" in result

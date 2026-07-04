from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from crabagent.serve.api import documents


class FakeOfficeManager:
    def __init__(self):
        self.binary_path = "/fake/officecli"
        self.set_calls = []
        self.batch_calls = []
        self.exec_calls = []
        self.stdin_calls = []
        self.get_element_result = {
            "results": [{"children": [{"path": "/body/p[2]"}]}],
        }
        self.query_result = {"results": [{"path": "/body/p[2]"}]}
        self.view_result = "<html><head></head><body>preview</body></html>"

    async def view_html(self, file_path: str):
        return SimpleNamespace(success=True, data=self.view_result, error="")

    async def set_props(self, file_path: str, element_path: str, props: dict):
        self.set_calls.append((file_path, element_path, props))
        return SimpleNamespace(success=True, error="")

    async def batch(self, file_path: str, commands: list[dict]):
        self.batch_calls.append((file_path, commands))
        return SimpleNamespace(success=True, error="")

    async def get_element(self, file_path: str, element_path: str, depth: int = 1):
        return SimpleNamespace(success=True, data=self.get_element_result, error="")

    async def add_element(self, file_path: str, parent_path: str, element_type: str, props: dict):
        self.exec_calls.append((("add_element", file_path, parent_path, element_type, props), 60))
        return SimpleNamespace(success=True, error="")

    async def remove_element(self, file_path: str, element_path: str):
        self.exec_calls.append((("remove", file_path, element_path), 60))
        return SimpleNamespace(success=True, error="")

    async def exec(self, *args: str, timeout: int = 60):
        self.exec_calls.append((args, timeout))
        return SimpleNamespace(success=True, error="")

    async def _exec_with_stdin(self, cmd: list[str], stdin_data: bytes | None = None, timeout: int = 60):
        self.stdin_calls.append((cmd, stdin_data, timeout))
        if cmd[1] == "query":
            return SimpleNamespace(success=True, data=self.query_result, error="")
        return SimpleNamespace(success=True, data={"ok": True}, error="")


@pytest.fixture
def fake_user():
    return SimpleNamespace(id=7)


@pytest.fixture
def docs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(documents, "_get_docs_dir", lambda user_id, workspace="": tmp_path)
    monkeypatch.setattr(documents, "_backup_doc", lambda file_path: str(file_path) + ".bak")
    return tmp_path


@pytest.mark.asyncio
async def test_quick_edit_style_returns_partial_when_one_change_fails(
    docs_dir: Path,
    fake_user,
    monkeypatch: pytest.MonkeyPatch,
):
    target = docs_dir / "sheet.xlsx"
    target.write_text("stub", encoding="utf-8")
    manager = FakeOfficeManager()

    async def fake_set_props(file_path: str, element_path: str, props: dict):
        if element_path.endswith("row[2]"):
            return SimpleNamespace(success=False, error="boom")
        return SimpleNamespace(success=True, error="")

    manager.set_props = fake_set_props
    monkeypatch.setattr(documents, "get_office_manager", lambda: manager)
    monkeypatch.setattr(documents, "_ensure_officecli", lambda: _awaitable(True))

    req = documents.QuickEditStyleRequest(
        path="sheet.xlsx",
        changes=[
            documents.StyleChange(element="/Sheet1/col[A]", props={"width": 20}),
            documents.StyleChange(element="/Sheet1/row[2]", props={"height": 30}),
        ],
    )

    resp = await documents.quick_edit_style(req, user=fake_user)

    assert resp.status == "partial"
    assert len(resp.results) == 2
    assert any(item["success"] is False for item in resp.results)
    assert "succeeded" in resp.message
    assert "white-space: pre-wrap" in resp.preview_html


@pytest.mark.asyncio
async def test_quick_edit_style_rejects_empty_changes(
    docs_dir: Path,
    fake_user,
    monkeypatch: pytest.MonkeyPatch,
):
    target = docs_dir / "sheet.xlsx"
    target.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(documents, "get_office_manager", lambda: FakeOfficeManager())
    monkeypatch.setattr(documents, "_ensure_officecli", lambda: _awaitable(True))

    req = documents.QuickEditStyleRequest(path="sheet.xlsx", changes=[])

    with pytest.raises(HTTPException) as exc:
        await documents.quick_edit_style(req, user=fake_user)

    assert exc.value.status_code == 400
    assert exc.value.detail == "No changes provided"


@pytest.mark.asyncio
async def test_quick_edit_text_simple_replace_uses_batch_command(
    docs_dir: Path,
    fake_user,
    monkeypatch: pytest.MonkeyPatch,
):
    target = docs_dir / "doc.docx"
    target.write_text("stub", encoding="utf-8")
    manager = FakeOfficeManager()
    monkeypatch.setattr(documents, "get_office_manager", lambda: manager)
    monkeypatch.setattr(documents, "_ensure_officecli", lambda: _awaitable(True))

    req = documents.QuickEditTextRequest(path="doc.docx", old_text="hello", new_text="bye")
    resp = await documents.quick_edit_text(req, user=fake_user)

    assert resp.status == "ok"
    assert manager.stdin_calls
    cmd, stdin_data, timeout = manager.stdin_calls[0]
    assert cmd[:3] == ["/fake/officecli", "batch", str(target)]
    assert b'"find": "hello"' in stdin_data
    assert b'"replace": "bye"' in stdin_data
    assert timeout == 60


@pytest.mark.asyncio
async def test_quick_edit_text_rejects_blank_old_text(
    docs_dir: Path,
    fake_user,
    monkeypatch: pytest.MonkeyPatch,
):
    target = docs_dir / "doc.docx"
    target.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(documents, "get_office_manager", lambda: FakeOfficeManager())
    monkeypatch.setattr(documents, "_ensure_officecli", lambda: _awaitable(True))

    req = documents.QuickEditTextRequest(path="doc.docx", old_text="   ", new_text="bye")

    with pytest.raises(HTTPException) as exc:
        await documents.quick_edit_text(req, user=fake_user)

    assert exc.value.status_code == 400
    assert exc.value.detail == "old_text is required"


@pytest.mark.asyncio
async def test_quick_edit_text_split_mode_queries_and_inserts_paragraphs(
    docs_dir: Path,
    fake_user,
    monkeypatch: pytest.MonkeyPatch,
):
    target = docs_dir / "doc.docx"
    target.write_text("stub", encoding="utf-8")
    manager = FakeOfficeManager()
    monkeypatch.setattr(documents, "get_office_manager", lambda: manager)
    monkeypatch.setattr(documents, "_ensure_officecli", lambda: _awaitable(True))

    req = documents.QuickEditTextRequest(path="doc.docx", old_text="hello", new_text="one\ntwo")
    resp = await documents.quick_edit_text(req, user=fake_user)

    assert resp.status == "ok"
    assert len(manager.stdin_calls) == 2
    assert manager.stdin_calls[0][0][1] == "query"
    assert manager.stdin_calls[1][0][1] == "batch"
    assert len(manager.exec_calls) == 2
    assert manager.exec_calls[0][0][0] == "add"
    assert "text=one" in manager.exec_calls[0][0]
    assert "text=two" in manager.exec_calls[1][0]


@pytest.mark.asyncio
async def test_quick_edit_text_split_mode_requires_known_paragraph_position(
    docs_dir: Path,
    fake_user,
    monkeypatch: pytest.MonkeyPatch,
):
    target = docs_dir / "doc.docx"
    target.write_text("stub", encoding="utf-8")
    manager = FakeOfficeManager()
    manager.get_element_result = {"results": [{"children": [{"path": "/body/p[9]"}]}]}
    monkeypatch.setattr(documents, "get_office_manager", lambda: manager)
    monkeypatch.setattr(documents, "_ensure_officecli", lambda: _awaitable(True))

    req = documents.QuickEditTextRequest(path="doc.docx", old_text="hello", new_text="one\ntwo")

    with pytest.raises(HTTPException) as exc:
        await documents.quick_edit_text(req, user=fake_user)

    assert exc.value.status_code == 500
    assert exc.value.detail == "Could not determine paragraph position"


@pytest.mark.asyncio
async def test_quick_edit_text_split_mode_returns_404_when_paragraph_not_found(
    docs_dir: Path,
    fake_user,
    monkeypatch: pytest.MonkeyPatch,
):
    target = docs_dir / "doc.docx"
    target.write_text("stub", encoding="utf-8")
    manager = FakeOfficeManager()
    manager.query_result = {"results": []}
    monkeypatch.setattr(documents, "get_office_manager", lambda: manager)
    monkeypatch.setattr(documents, "_ensure_officecli", lambda: _awaitable(True))

    req = documents.QuickEditTextRequest(path="doc.docx", old_text="hello", new_text="one\ntwo")

    with pytest.raises(HTTPException) as exc:
        await documents.quick_edit_text(req, user=fake_user)

    assert exc.value.status_code == 404
    assert "Paragraph with text 'hello' not found" == exc.value.detail


@pytest.mark.asyncio
async def test_quick_edit_table_op_returns_error_payload_on_failed_batch(
    docs_dir: Path,
    fake_user,
    monkeypatch: pytest.MonkeyPatch,
):
    target = docs_dir / "sheet.xlsx"
    target.write_text("stub", encoding="utf-8")
    manager = FakeOfficeManager()

    async def fake_batch(file_path: str, commands: list[dict]):
        manager.batch_calls.append((file_path, commands))
        return SimpleNamespace(success=False, error="cannot merge")

    manager.batch = fake_batch
    monkeypatch.setattr(documents, "get_office_manager", lambda: manager)
    monkeypatch.setattr(documents, "_ensure_officecli", lambda: _awaitable(True))

    req = documents.TableOpRequest(path="sheet.xlsx", operation="merge_cells", params={"range": "A1:C3"})
    resp = await documents.quick_edit_table_op(req, user=fake_user)

    assert resp.status == "error"
    assert resp.error == "cannot merge"
    assert manager.batch_calls[0][1][0]["props"] == {"merge": True}


@pytest.mark.asyncio
async def test_quick_edit_theme_rejects_non_pptx(
    docs_dir: Path,
    fake_user,
    monkeypatch: pytest.MonkeyPatch,
):
    target = docs_dir / "doc.docx"
    target.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(documents, "get_office_manager", lambda: FakeOfficeManager())
    monkeypatch.setattr(documents, "_ensure_officecli", lambda: _awaitable(True))

    req = documents.ThemeEditRequest(path="doc.docx", props={"accent1": "4472C4"})
    with pytest.raises(HTTPException) as exc:
        await documents.quick_edit_theme(req, user=fake_user)

    assert exc.value.status_code == 400
    assert ".pptx" in exc.value.detail


@pytest.mark.asyncio
async def test_quick_edit_theme_rejects_empty_props(
    docs_dir: Path,
    fake_user,
    monkeypatch: pytest.MonkeyPatch,
):
    target = docs_dir / "deck.pptx"
    target.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(documents, "get_office_manager", lambda: FakeOfficeManager())
    monkeypatch.setattr(documents, "_ensure_officecli", lambda: _awaitable(True))

    req = documents.ThemeEditRequest(path="deck.pptx", props={})

    with pytest.raises(HTTPException) as exc:
        await documents.quick_edit_theme(req, user=fake_user)

    assert exc.value.status_code == 400
    assert exc.value.detail == "No theme props provided"


@pytest.mark.asyncio
async def test_quick_edit_theme_returns_error_status_when_set_props_fails(
    docs_dir: Path,
    fake_user,
    monkeypatch: pytest.MonkeyPatch,
):
    target = docs_dir / "deck.pptx"
    target.write_text("stub", encoding="utf-8")
    manager = FakeOfficeManager()

    async def failing_set_props(file_path: str, element_path: str, props: dict):
        return SimpleNamespace(success=False, error="theme failed")

    manager.set_props = failing_set_props
    monkeypatch.setattr(documents, "get_office_manager", lambda: manager)
    monkeypatch.setattr(documents, "_ensure_officecli", lambda: _awaitable(True))

    req = documents.ThemeEditRequest(path="deck.pptx", props={"accent1": "4472C4"})
    resp = await documents.quick_edit_theme(req, user=fake_user)

    assert resp.status == "error"
    assert resp.results[0]["error"] == "theme failed"
    assert "主题更新失败" in resp.message


@pytest.mark.asyncio
async def test_quick_edit_structure_handles_invalid_operation_object(
    docs_dir: Path,
    fake_user,
    monkeypatch: pytest.MonkeyPatch,
):
    target = docs_dir / "deck.pptx"
    target.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(documents, "get_office_manager", lambda: FakeOfficeManager())
    monkeypatch.setattr(documents, "_ensure_officecli", lambda: _awaitable(True))

    req = documents.StructureEditRequest(
        path="deck.pptx",
        operations=[{"command": "unknown"}, {"command": "remove", "path": "/slide[1]"}],
    )
    resp = await documents.quick_edit_structure(req, user=fake_user)

    assert resp.status == "partial"
    assert resp.results[0]["success"] is False
    assert resp.results[1]["success"] is True


@pytest.mark.asyncio
async def test_quick_edit_structure_rejects_empty_operations(
    docs_dir: Path,
    fake_user,
    monkeypatch: pytest.MonkeyPatch,
):
    target = docs_dir / "deck.pptx"
    target.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(documents, "get_office_manager", lambda: FakeOfficeManager())
    monkeypatch.setattr(documents, "_ensure_officecli", lambda: _awaitable(True))

    req = documents.StructureEditRequest(path="deck.pptx", operations=[])

    with pytest.raises(HTTPException) as exc:
        await documents.quick_edit_structure(req, user=fake_user)

    assert exc.value.status_code == 400
    assert exc.value.detail == "No operations provided"


@pytest.mark.asyncio
async def test_quick_edit_structure_runs_set_and_add_operations(
    docs_dir: Path,
    fake_user,
    monkeypatch: pytest.MonkeyPatch,
):
    target = docs_dir / "deck.pptx"
    target.write_text("stub", encoding="utf-8")
    manager = FakeOfficeManager()
    monkeypatch.setattr(documents, "get_office_manager", lambda: manager)
    monkeypatch.setattr(documents, "_ensure_officecli", lambda: _awaitable(True))

    req = documents.StructureEditRequest(
        path="deck.pptx",
        operations=[
            {"command": "set", "path": "/slide[1]", "props": {"title": "Hello"}},
            {"command": "add", "parent": "/slide[1]", "type": "shape", "props": {"text": "Body"}},
        ],
    )
    resp = await documents.quick_edit_structure(req, user=fake_user)

    assert resp.status == "ok"
    assert manager.set_calls[0][1] == "/slide[1]"
    assert manager.exec_calls[0][0][0] == "add_element"
    assert resp.results[0]["target"] == "/slide[1]"
    assert resp.results[1]["target"] == "/slide[1] -> shape"


@pytest.mark.asyncio
async def test_preview_document_returns_installing_payload_when_officecli_pending(
    fake_user,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(documents, "_ensure_officecli", lambda: _awaitable(False))

    resp = await documents.preview_document("doc.docx", user=fake_user)

    assert isinstance(resp, JSONResponse)
    assert resp.status_code == 503
    assert b'"installing":true' in resp.body


def test_safe_path_blocks_traversal(tmp_path: Path):
    with pytest.raises(HTTPException) as exc:
        documents._safe_path(tmp_path, "../evil.docx")

    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    ("operation", "params", "expected"),
    [
        ("insert_row", {"after_row": 3}, {"command": "add", "after": "/Sheet1/row[3]"}),
        ("delete_col", {"col_letter": "B"}, {"command": "remove", "path": "/Sheet1/col[B]"}),
        ("set_formula", {"cell": "C2", "formula": "SUM(A1:A2)"}, {"props": {"formula": "SUM(A1:A2)"}}),
    ],
)
def test_build_batch_cmd_covers_multiple_operations(operation: str, params: dict, expected: dict):
    req = documents.TableOpRequest(path="sheet.xlsx", operation=operation, params=params)

    command = documents._build_batch_cmd(req)

    for key, value in expected.items():
        assert command[key] == value


def test_build_batch_cmd_returns_none_for_invalid_params():
    assert documents._build_batch_cmd(documents.TableOpRequest(path="x.xlsx", operation="merge_cells", params={})) is None
    assert documents._build_batch_cmd(documents.TableOpRequest(path="x.xlsx", operation="set_cell_style", params={"cell": "A1", "props": {}})) is None
    assert documents._build_batch_cmd(documents.TableOpRequest(path="x.xlsx", operation="unknown", params={})) is None


def test_fix_html_newlines_injects_css_only_when_html_present():
    html = "<html><head></head><body>line1\nline2</body></html>"

    fixed = documents._fix_html_newlines(html)

    assert "white-space: pre-wrap" in fixed
    assert documents._fix_html_newlines(None) is None


def test_fix_html_newlines_injects_css_without_head():
    html = "<html><body>preview</body></html>"

    fixed = documents._fix_html_newlines(html)

    assert fixed.startswith("<style>.page, .page-body, .page * { white-space: pre-wrap !important; }</style>")


async def _awaitable(value):
    return value

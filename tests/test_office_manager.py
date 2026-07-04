from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from crabagent.core.office import manager as office_manager_module
from crabagent.core.office.manager import OfficeManager


@pytest.mark.asyncio
async def test_exec_returns_install_hint_when_unavailable():
    manager = OfficeManager()

    result = await manager.exec("view", "demo.docx", "html")

    assert result.success is False
    assert "OfficeCLI" in result.error


@pytest.mark.asyncio
async def test_view_text_builds_expected_args(monkeypatch: pytest.MonkeyPatch):
    manager = OfficeManager()
    manager._available = True
    manager._binary_path = "/fake/officecli"
    captured = {}

    async def fake_exec(*args: str, timeout: int = 60):
        captured["args"] = args
        captured["timeout"] = timeout
        return SimpleNamespace(success=True)

    monkeypatch.setattr(manager, "exec", fake_exec)
    await manager.view_text("demo.xlsx", max_lines=10, sheet="Sheet1", cols="A:C", start=5)

    assert captured["args"] == (
        "view",
        "demo.xlsx",
        "text",
        "--max-lines",
        "10",
        "--start",
        "5",
        "--sheet",
        "Sheet1",
        "--cols",
        "A:C",
    )
    assert captured["timeout"] == 60


@pytest.mark.asyncio
async def test_add_element_supports_index_and_table_data(monkeypatch: pytest.MonkeyPatch):
    manager = OfficeManager()
    manager._available = True
    manager._binary_path = "/fake/officecli"
    captured = {}

    async def fake_exec(*args: str, timeout: int = 60):
        captured["args"] = args
        return SimpleNamespace(success=True)

    monkeypatch.setattr(manager, "exec", fake_exec)
    await manager.add_element(
        "deck.pptx",
        "/slide[1]",
        "table",
        {"index": 2, "data": [["A", "B"], [1, 2]], "style": "medium1"},
    )

    assert captured["args"] == (
        "add",
        "deck.pptx",
        "/slide[1]",
        "--type",
        "table",
        "--index",
        "2",
        "--prop",
        "data=A,B;1,2",
        "--prop",
        "style=medium1",
    )


@pytest.mark.asyncio
async def test_add_element_supports_before_and_after(monkeypatch: pytest.MonkeyPatch):
    manager = OfficeManager()
    manager._available = True
    manager._binary_path = "/fake/officecli"
    captured = {}

    async def fake_exec(*args: str, timeout: int = 60):
        captured["args"] = args
        return SimpleNamespace(success=True)

    monkeypatch.setattr(manager, "exec", fake_exec)
    await manager.add_element(
        "doc.docx",
        "/body",
        "paragraph",
        {"after": "/body/p[1]", "before": "/body/p[3]", "text": "hello"},
    )

    assert captured["args"] == (
        "add",
        "doc.docx",
        "/body",
        "--type",
        "paragraph",
        "--after",
        "/body/p[1]",
        "--before",
        "/body/p[3]",
        "--prop",
        "text=hello",
    )


@pytest.mark.asyncio
async def test_batch_serializes_commands_to_json(monkeypatch: pytest.MonkeyPatch):
    manager = OfficeManager()
    manager._available = True
    manager._binary_path = "/fake/officecli"
    captured = {}

    async def fake_exec(*args: str, timeout: int = 60):
        captured["args"] = args
        return SimpleNamespace(success=True)

    monkeypatch.setattr(manager, "exec", fake_exec)

    await manager.batch("sheet.xlsx", [{"command": "set", "path": "/Sheet1/A1", "props": {"text": "x"}}])

    assert captured["args"] == (
        "batch",
        "sheet.xlsx",
        "--commands",
        json.dumps([{"command": "set", "path": "/Sheet1/A1", "props": {"text": "x"}}]),
    )


@pytest.mark.asyncio
async def test_exec_with_stdin_parses_json_payload(monkeypatch: pytest.MonkeyPatch):
    manager = OfficeManager()
    manager._available = True
    manager._binary_path = "/fake/officecli"

    class FakeProc:
        returncode = 0

        async def communicate(self, input=None):
            payload = {"success": True, "data": {"value": 42}}
            return json.dumps(payload).encode(), b""

    async def fake_create(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(office_manager_module.asyncio, "create_subprocess_exec", fake_create)

    result = await manager._exec_with_stdin(["/fake/officecli", "get"], stdin_data=b"{}")

    assert result.success is True
    assert result.data == {"value": 42}
    stats = manager.get_perf_stats()
    assert stats["get"]["count"] == 1


@pytest.mark.asyncio
async def test_exec_with_stdin_returns_plain_text_when_json_invalid(monkeypatch: pytest.MonkeyPatch):
    manager = OfficeManager()
    manager._available = True
    manager._binary_path = "/fake/officecli"

    class FakeProc:
        returncode = 0

        async def communicate(self, input=None):
            return b'{"broken": ', b""

    async def fake_create(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(office_manager_module.asyncio, "create_subprocess_exec", fake_create)

    result = await manager._exec_with_stdin(["/fake/officecli", "view"])

    assert result.success is True
    assert result.data == '{"broken": '
    assert result.raw_output == '{"broken": '


@pytest.mark.asyncio
async def test_exec_with_stdin_returns_error_for_nonzero_exit(monkeypatch: pytest.MonkeyPatch):
    manager = OfficeManager()
    manager._available = True
    manager._binary_path = "/fake/officecli"

    class FakeProc:
        returncode = 7

        async def communicate(self, input=None):
            return b"partial", b"broken"

    async def fake_create(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(office_manager_module.asyncio, "create_subprocess_exec", fake_create)
    result = await manager._exec_with_stdin(["/fake/officecli", "batch"])

    assert result.success is False
    assert result.error == "broken"
    assert result.raw_output == "partial"


@pytest.mark.asyncio
async def test_exec_with_stdin_handles_timeout(monkeypatch: pytest.MonkeyPatch):
    manager = OfficeManager()
    manager._available = True
    manager._binary_path = "/fake/officecli"

    class FakeProc:
        returncode = 0

        def communicate(self, input=None):
            return None

    async def fake_create(*args, **kwargs):
        return FakeProc()

    async def fake_wait_for(awaitable, timeout):
        raise TimeoutError

    monkeypatch.setattr(office_manager_module.asyncio, "create_subprocess_exec", fake_create)
    monkeypatch.setattr(office_manager_module.asyncio, "wait_for", fake_wait_for)

    result = await manager._exec_with_stdin(["/fake/officecli", "view"], timeout=3)

    assert result.success is False
    assert "3s" in result.error


@pytest.mark.asyncio
async def test_exec_with_stdin_marks_binary_unavailable_on_missing_file(monkeypatch: pytest.MonkeyPatch):
    manager = OfficeManager()
    manager._available = True
    manager._binary_path = "/fake/officecli"

    async def fake_create(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(office_manager_module.asyncio, "create_subprocess_exec", fake_create)

    result = await manager._exec_with_stdin(["/fake/officecli", "view"])

    assert result.success is False
    assert result.error == "OfficeCLI binary not found"
    assert manager.available is False


@pytest.mark.asyncio
async def test_install_fails_on_checksum_mismatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    manager = OfficeManager()

    monkeypatch.setattr(office_manager_module, "_determine_asset", lambda: "officecli-mac-x64")

    async def fake_version():
        return "v1.2.3"

    monkeypatch.setattr(office_manager_module, "_resolve_latest_version", fake_version)

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(office_manager_module.Path, "home", lambda: home)

    class FakeResponse:
        def __init__(self, *, content=b"", text=""):
            self.content = content
            self.text = text

        def raise_for_status(self):
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, timeout=None):
            if url.endswith("SHA256SUMS"):
                return FakeResponse(text="deadbeef officecli-mac-x64\n")
            return FakeResponse(content=b"payload")

    monkeypatch.setitem(__import__("sys").modules, "httpx", SimpleNamespace(AsyncClient=lambda **kwargs: FakeClient()))

    ok = await manager.install()

    assert ok is False
    assert manager.get_install_status()["status"] == "failed"
    assert manager.get_install_status()["message"] == "Checksum mismatch"


@pytest.mark.asyncio
async def test_install_fails_when_asset_is_unsupported():
    manager = OfficeManager()

    original = office_manager_module._determine_asset
    office_manager_module._determine_asset = lambda: None
    try:
        ok = await manager.install()
    finally:
        office_manager_module._determine_asset = original

    assert ok is False
    assert manager.get_install_status()["status"] == "failed"
    assert "Unsupported platform" in manager.get_install_status()["message"]


@pytest.mark.asyncio
async def test_detect_uses_probe_locations_when_not_in_path(monkeypatch: pytest.MonkeyPatch):
    manager = OfficeManager()
    candidate = "/tmp/officecli"

    monkeypatch.setattr(office_manager_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(office_manager_module, "_PROBE_LOCATIONS", [candidate])
    monkeypatch.setattr(office_manager_module.os.path, "isfile", lambda path: path == candidate)
    monkeypatch.setattr(office_manager_module.os, "access", lambda path, mode: path == candidate)

    async def fake_set_binary(path: str):
        manager._binary_path = path
        manager._available = True
        return True

    monkeypatch.setattr(manager, "_set_binary", fake_set_binary)

    ok = await manager.detect()

    assert ok is True
    assert manager.binary_path == candidate

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from crabagent.serve.api.files import _is_relative_to


def test_is_relative_to_detects_nested_path(tmp_path: Path):
    parent = tmp_path / "folder"
    child = parent / "nested"
    child.mkdir(parents=True)

    assert _is_relative_to(child, parent)
    assert not _is_relative_to(parent, child)


def test_relative_path_resolution_blocks_workspace_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from crabagent.serve.api import files
    from crabagent.core.config import settings

    monkeypatch.setattr(settings, "workspace", tmp_path)
    with pytest.raises(HTTPException, match="Path outside workspace"):
        files._resolve_file_path("../outside")


@pytest.mark.asyncio
async def test_file_editor_rejects_stale_save(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from crabagent.core.config import settings
    from crabagent.serve.api import files

    monkeypatch.setattr(settings, "workspace", tmp_path)
    target = tmp_path / "test.txt"
    target.write_text("original")
    result = await files.read_file(path="test.txt", absolute=False, user=SimpleNamespace(id=1), db=None)
    target.write_text("other")
    req = files.WriteFileRequest(path="test.txt", content="draft", expected_version=result["version"])
    with pytest.raises(HTTPException) as exc:
        await files.write_file(req, user=SimpleNamespace(id=1), db=None)
    assert exc.value.status_code == 409
    assert target.read_text() == "other"


@pytest.mark.asyncio
async def test_file_editor_requires_base_version(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from crabagent.core.config import settings
    from crabagent.serve.api import files

    monkeypatch.setattr(settings, "workspace", tmp_path)
    with pytest.raises(HTTPException) as exc:
        await files.write_file(
            files.WriteFileRequest(path="test.txt", content="draft"), user=SimpleNamespace(id=1), db=None
        )
    assert exc.value.status_code == 428


@pytest.mark.asyncio
async def test_version_endpoint_detects_external_modification(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from crabagent.core.config import settings
    from crabagent.serve.api.files import get_file_version

    monkeypatch.setattr(settings, "workspace", tmp_path)
    target = tmp_path / "data.txt"
    target.write_text("one")
    before = await get_file_version("data.txt", absolute=False, user=SimpleNamespace(id=1))
    target.write_text("two")
    after = await get_file_version("data.txt", absolute=False, user=SimpleNamespace(id=1))
    assert before["version"] != after["version"]
    target.unlink()
    deleted = await get_file_version("data.txt", absolute=False, user=SimpleNamespace(id=1))
    assert deleted["version"] == "missing"

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

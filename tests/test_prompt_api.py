from __future__ import annotations

import base64
import tempfile
from pathlib import Path

from crabagent.serve.api import prompt as prompt_api


def test_save_image_temp_writes_file_and_returns_metadata(tmp_path: Path, monkeypatch):
    payload = base64.b64encode(b"png-bytes").decode()
    data_url = f"data:image/png;base64,{payload}"

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    result = prompt_api._save_image_temp(data_url)

    assert result["mime"] == "image/png"
    assert result["size_kb"] >= 0
    assert Path(result["file_path"]).exists()
    assert Path(result["file_path"]).read_bytes() == b"png-bytes"


def test_extract_local_images_ignores_missing_and_non_image_files(tmp_path: Path):
    text_file = tmp_path / "note.txt"
    text_file.write_text("hello", encoding="utf-8")
    image_file = tmp_path / "a.png"
    image_file.write_bytes(b"fake-image")

    message = f"see {image_file} and {text_file} and /no/such/file.jpg"
    blocks = prompt_api._extract_local_images(message)

    assert len(blocks) == 1
    assert blocks[0]["type"] == "image_url"
    assert blocks[0]["file_path"] == str(image_file)
    assert blocks[0]["mime"] == "image/png"
    assert blocks[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_extract_local_images_handles_parenthesized_paths(tmp_path: Path):
    image_file = tmp_path / "b.jpg"
    image_file.write_bytes(b"jpg-bytes")

    message = f"please inspect ({image_file}) now"
    blocks = prompt_api._extract_local_images(message)

    assert len(blocks) == 1
    assert blocks[0]["file_path"] == str(image_file)
    assert blocks[0]["mime"] == "image/jpeg"


def test_mermaid_generation_instructions_require_conservative_flowchart_syntax():
    instructions = prompt_api.MERMAID_GENERATION_INSTRUCTIONS

    assert '`flowchart LR` or `flowchart TD`' in instructions
    assert '`Q -->|Yes| A`' in instructions
    assert 'Never use the ambiguous `-- label -->` form.' in instructions
    assert 'Do not use HTML (including `<br/>`)' in instructions

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

import pytest

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

    assert "`flowchart LR` or `flowchart TD`" in instructions
    assert "`Q -->|Yes| A`" in instructions
    assert "Never use the ambiguous `-- label -->` form." in instructions
    assert "Do not use HTML (including `<br/>`)" in instructions


async def _owned_conversation(*args):
    from types import SimpleNamespace

    return SimpleNamespace(id=1)


@pytest.mark.asyncio
async def test_running_prompt_accepts_followup_without_starting_second_run(monkeypatch):
    from types import SimpleNamespace

    from crabagent.core.agent.context import AgentContext

    context = AgentContext(workspace=Path.cwd())
    context.metadata["_accept_followups"] = True
    monkeypatch.setattr(prompt_api, "get_owned_conversation", _owned_conversation)
    monkeypatch.setattr(prompt_api, "_tasks", {"session": SimpleNamespace(done=lambda: False)})
    monkeypatch.setattr(prompt_api, "_contexts", {"session": context})
    result = await prompt_api.prompt_async(
        "session",
        prompt_api.PromptRequest(message="new instructions", images=["data:image/png;base64,eA=="]),
        None,
        SimpleNamespace(id=1),
        None,
    )
    assert result["status"] == "queued"
    assert context.metadata["_pending_user_messages"][0][0]["text"] == "new instructions"


@pytest.mark.asyncio
async def test_finishing_prompt_does_not_accept_followup(monkeypatch):
    from types import SimpleNamespace

    from fastapi import HTTPException

    from crabagent.core.agent.context import AgentContext

    context = AgentContext(workspace=Path.cwd())
    monkeypatch.setattr(prompt_api, "get_owned_conversation", _owned_conversation)
    monkeypatch.setattr(prompt_api, "_tasks", {"session": SimpleNamespace(done=lambda: False)})
    monkeypatch.setattr(prompt_api, "_contexts", {"session": context})
    with pytest.raises(HTTPException) as exc:
        await prompt_api.prompt_async("session", prompt_api.PromptRequest(message="hi"), None, None, None)
    assert exc.value.status_code == 409

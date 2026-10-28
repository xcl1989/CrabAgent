"""Tests for image generation tool helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.tools import image as image_module


class TestResolveModel:
    def test_passes_through_model_with_slash(self):
        assert image_module._resolve_model("openai", "openai/dall-e-3") == "openai/dall-e-3"

    def test_chatgpt_provider_prefix(self):
        assert image_module._resolve_model("chatgpt", "image-2") == "chatgpt/image-2"

    def test_openai_provider_no_prefix(self):
        assert image_module._resolve_model("openai", "dall-e-3") == "dall-e-3"

    def test_unknown_provider(self):
        assert image_module._resolve_model("custom", "my-model") == "my-model"


class TestImageDir:
    def test_creates_directory(self, tmp_path: Path):
        ctx = AgentContext(workspace=tmp_path)
        result = image_module._image_dir(ctx)
        assert result.exists()
        assert result == tmp_path / ".crabagent" / "assets" / "images"

    def test_uses_cwd_when_no_workspace(self):
        ctx = SimpleNamespace()
        result = image_module._image_dir(ctx)
        assert result.exists()


class TestSaveImage:
    def test_strips_data_prefix(self, tmp_path: Path):
        import base64

        raw = b"\x89PNG\r\n\x1a\n"
        b64 = "data:image/png;base64," + base64.b64encode(raw).decode()

        path = image_module._save_image(b64, tmp_path, "test", 0)
        assert path.exists()
        assert path.read_bytes() == raw

    def test_handles_raw_base64(self, tmp_path: Path):
        import base64

        raw = b"\x89PNG test data"
        b64 = base64.b64encode(raw).decode()

        path = image_module._save_image(b64, tmp_path, "img", 1)
        assert path.exists()
        assert path.name == "img-2.png"

    def test_index_zero_suffix(self, tmp_path: Path):
        import base64

        b64 = base64.b64encode(b"x").decode()
        path = image_module._save_image(b64, tmp_path, "shot", 0)
        assert path.name == "shot-1.png"


class TestGuessExtension:
    @pytest.mark.parametrize(
        ("content_type", "expected"),
        [
            ("image/jpeg", ".jpg"),
            ("image/jpg", ".jpg"),
            ("image/webp", ".webp"),
            ("image/avif", ".avif"),
            ("image/png", ".png"),
            (None, ".png"),
            ("application/octet-stream", ".png"),
        ],
    )
    def test_guess_extension(self, content_type, expected):
        assert image_module._guess_extension(content_type) == expected


class TestReferencePaths:
    @pytest.fixture
    def references(self, tmp_path):
        paths = [tmp_path / "scene.png", tmp_path / "person.jpg"]
        for index, path in enumerate(paths):
            path.write_bytes(f"reference-{index}".encode())
        return paths

    def test_explicit_paths_preserve_order(self, references, tmp_path):
        ctx = SimpleNamespace(workspace=tmp_path)
        assert image_module._resolve_reference_paths("", [p.name for p in references], ctx) == references

    def test_defaults_to_all_current_attachments(self, references):
        ctx = SimpleNamespace(metadata={"attached_image_paths": [str(p) for p in references]})
        assert image_module._resolve_reference_paths("", None, ctx) == references

    def test_legacy_path_overrides_attachments(self, references):
        ctx = SimpleNamespace(metadata={"attached_image_paths": [str(references[1])]})
        assert image_module._resolve_reference_paths(str(references[0]), None, ctx) == references[:1]

    @pytest.mark.parametrize("paths", [[], ["missing.png"], [""], [None], "scene.png", ["x.png"] * 17])
    def test_invalid_input_is_not_silently_skipped(self, paths, tmp_path):
        with pytest.raises(ValueError):
            image_module._resolve_reference_paths("", paths, SimpleNamespace(workspace=tmp_path))

    def test_invalid_second_reference_rejects_entire_request(self, references):
        with pytest.raises(ValueError, match="Reference image 2"):
            image_module._resolve_reference_paths("", [str(references[0]), "missing.png"], None)

    def test_conflicting_parameters_rejected(self, references):
        with pytest.raises(ValueError, match="not both"):
            image_module._resolve_reference_paths(str(references[0]), [str(references[1])], None)

    def test_unsupported_extension_rejected(self, tmp_path):
        path = tmp_path / "text.txt"
        path.write_text("not an image")
        with pytest.raises(ValueError, match="unsupported"):
            image_module._resolve_reference_paths(str(path), None, None)

    def test_sixteen_references_allowed(self, references):
        paths = [str(references[0])] * 16
        assert len(image_module._resolve_reference_paths("", paths, None)) == 16


class TestImageEdit:
    @pytest.fixture
    def setup_edit(self, tmp_path, monkeypatch):
        from unittest.mock import AsyncMock

        from crabagent.core import provider_store

        paths = [tmp_path / "scene.png", tmp_path / "person.jpg"]
        for index, path in enumerate(paths):
            path.write_bytes(f"reference-{index}".encode())
        provider = SimpleNamespace(provider_type="openai", name="test")
        monkeypatch.setattr(provider_store, "get_default_provider", AsyncMock(return_value=provider))
        ctx = SimpleNamespace(workspace=tmp_path, metadata={"attached_image_paths": [str(p) for p in paths]})
        return ctx, paths, provider

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["explicit", "attached", "legacy"])
    async def test_openai_payload_and_result(self, setup_edit, monkeypatch, mode):
        import base64
        import json
        from unittest.mock import AsyncMock

        import litellm

        ctx, paths, _ = setup_edit
        mock_edit = AsyncMock(return_value={"data": [{"b64_json": base64.b64encode(b"edited").decode()}]})
        monkeypatch.setattr(litellm, "aimage_edit", mock_edit)
        kwargs = {}
        if mode == "explicit":
            kwargs["reference_image_paths"] = [str(p) for p in paths]
        elif mode == "legacy":
            kwargs["reference_image_path"] = str(paths[0])
        result = json.loads(await image_module.image_edit("Replace image 1 person with image 2", context=ctx, **kwargs))
        expected = paths[:1] if mode == "legacy" else paths
        assert result["reference_image"] == str(paths[0])
        assert result["reference_images"] == [str(p) for p in expected]
        assert Path(result["images"][0]["path"]).read_bytes() == b"edited"
        sent = mock_edit.call_args.kwargs["image"]
        if mode == "legacy":
            assert sent == paths[0].read_bytes()
        else:
            assert sent == [(p.name, p.read_bytes(), mime) for p, mime in zip(paths, ["image/png", "image/jpeg"])]

    @pytest.mark.asyncio
    async def test_chatgpt_receives_all_references(self, setup_edit, monkeypatch):
        import json
        from unittest.mock import AsyncMock

        ctx, paths, provider = setup_edit
        provider.provider_type = "chatgpt"
        edit = AsyncMock(return_value=b"edited")
        monkeypatch.setattr(image_module, "_chatgpt_image_edit", edit)
        result = json.loads(await image_module.image_edit("Replace person", context=ctx))
        edit.assert_awaited_once_with("Replace person", paths)
        assert result["reference_images"] == [str(p) for p in paths]

    @pytest.mark.asyncio
    async def test_invalid_reference_never_calls_provider(self, setup_edit, monkeypatch):
        import json
        from unittest.mock import AsyncMock

        import litellm

        ctx, paths, _ = setup_edit
        edit = AsyncMock()
        monkeypatch.setattr(litellm, "aimage_edit", edit)
        result = json.loads(
            await image_module.image_edit(
                "Replace person", context=ctx, reference_image_paths=[str(paths[0]), "missing.png"]
            )
        )
        assert "Reference image 2" in result["error"]
        edit.assert_not_called()

    @pytest.mark.asyncio
    async def test_chatgpt_http_payload(self, setup_edit, monkeypatch):
        import base64
        from unittest.mock import AsyncMock

        import httpx

        from crabagent.serve.api import chatgpt_auth

        _, paths, _ = setup_edit
        monkeypatch.setattr(chatgpt_auth, "get_codex_request_headers", AsyncMock(return_value={}))
        monkeypatch.setattr(chatgpt_auth, "get_codex_model", AsyncMock(return_value="test-model"))
        raw_image = b"\x89PNG\r\n\x1a\n" + b"x" * 1000
        captured = {}

        class StreamResponse:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def aiter_bytes(self):
                yield b'data: {"result":"' + base64.b64encode(raw_image) + b'"}\n\n'

        class Client:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def stream(self, *args, **kwargs):
                captured.update(kwargs["json"])
                return StreamResponse()

        monkeypatch.setattr(httpx, "AsyncClient", Client)
        assert await image_module._chatgpt_image_edit("Swap person", paths) == raw_image
        content = captured["input"][0]["content"]
        images = [part["image_url"] for part in content if part["type"] == "input_image"]
        assert images == [
            f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"
            for p, mime in zip(paths, ["image/png", "image/jpeg"])
        ]
        assert [part["text"] for part in content[1:] if part["type"] == "input_text"] == ["Image 1:", "Image 2:"]

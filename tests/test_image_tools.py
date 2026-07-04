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

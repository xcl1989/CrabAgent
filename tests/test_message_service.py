from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from crabagent.core.database import Base, Message
from crabagent.serve.services import message as message_service


def _make_msg(**kwargs):
    return Message(**kwargs)


def test_message_to_dict_handles_compressed_role_and_json_content():
    msg = _make_msg(conversation_id=1, sequence=1, role="compress", content="summary text")
    d = message_service.message_to_dict(msg)
    assert d["role"] == "user"
    assert d["content"] == "summary text"


def test_message_to_dict_parses_list_content_json():
    msg = _make_msg(
        conversation_id=1,
        sequence=2,
        role="tool",
        content=json.dumps([{"type": "text", "text": "hello"}]),
    )
    d = message_service.message_to_dict(msg)
    assert isinstance(d["content"], list)
    assert d["content"][0]["text"] == "hello"


def test_message_to_dict_parses_tool_calls_json():
    msg = _make_msg(
        conversation_id=1,
        sequence=3,
        role="assistant",
        content="",
        tool_calls=json.dumps([{"id": "c1", "type": "function", "function": {"name": "x"}}]),
    )
    d = message_service.message_to_dict(msg)
    assert d["tool_calls"][0]["id"] == "c1"


def test_message_to_response_inlines_screenshot(tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    msg = _make_msg(conversation_id=1, sequence=4, role="screenshot", content=str(img))
    # With strip_images=True (default), image data is not inlined
    d = message_service.message_to_response(msg)
    assert d.get("has_images") is True
    assert "image_data" not in d
    # With strip_images=False, image data is inlined
    d = message_service.message_to_response(msg, strip_images=False)
    assert d["image_data"].startswith("data:image/png;base64,")


def test_message_to_response_handles_screenshot_missing_file():
    msg = _make_msg(conversation_id=1, sequence=5, role="screenshot", content="/nope.png")
    d = message_service.message_to_response(msg)
    assert "image_data" not in d


def test_strip_base64_images_from_user_content():
    """User message with embedded base64 image should be stripped in list view."""
    big_b64 = "A" * 10000  # simulate large base64 data
    content = json.dumps([
        {"type": "text", "text": "看这张图"},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{big_b64}"}},
    ])
    msg = _make_msg(conversation_id=1, sequence=6, role="user", content=content)
    d = message_service.message_to_response(msg, strip_images=True)
    assert d.get("has_images") is True
    assert big_b64 not in d["content"]  # base64 data stripped
    # Text content preserved
    assert "看这张图" in d["content"]


def test_strip_base64_images_no_images():
    """Messages without images should be unaffected."""
    msg = _make_msg(conversation_id=1, sequence=7, role="user", content="hello world")
    d = message_service.message_to_response(msg, strip_images=True)
    assert d["content"] == "hello world"
    assert "has_images" not in d


@pytest.mark.asyncio
async def test_save_message_persists_via_async_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    class FakeAsyncSession:
        def __init__(self):
            from sqlalchemy.orm import Session as SyncSession

            self._sync = SyncSession(engine)

        async def __aenter__(self):
            return self._sync

        async def __aexit__(self, *a):
            return False

        async def commit(self):
            self._sync.commit()

        async def refresh(self, obj):
            self._sync.refresh(obj)

        def add(self, obj):
            self._sync.add(obj)

    db = FakeAsyncSession()

    msg = await message_service.save_message(
        db=db,
        conversation_id=1,
        sequence=1,
        role="user",
        content="hi",
    )

    assert msg.id is not None
    assert msg.content == "hi"


def test_save_message_signature_has_expected_params():
    import inspect

    sig = inspect.signature(message_service.save_message)
    assert "conversation_id" in sig.parameters
    assert "branch_id" in sig.parameters
    assert "reasoning_content" in sig.parameters


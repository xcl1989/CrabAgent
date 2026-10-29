import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from crabagent.core.wechat.client import IncomingMessage, MediaAttachment
from crabagent.core.wechat.config import WeChatConfig
from crabagent.core.wechat.message import WeChatMessageLoop


@pytest.fixture(autouse=True)
def authorize(monkeypatch):
    monkeypatch.setattr(
        "crabagent.core.wechat.config.load_config",
        AsyncMock(return_value=WeChatConfig(enabled=True, allowed_users=["a", "b"])),
    )


@pytest.mark.asyncio
async def test_followups_and_parallel_users(tmp_path):
    loop = WeChatMessageLoop(SimpleNamespace())
    started = asyncio.Event()
    release = asyncio.Event()
    contexts = {}

    async def handler(msg, active):
        context = SimpleNamespace(workspace=tmp_path, metadata={"_accept_followups": True}, budget_exhausted=False)
        contexts[msg.from_user] = context
        active["context"] = context
        active["ready"].set()
        started.set()
        await release.wait()

    loop._default_handler = handler
    await loop._dispatch(IncomingMessage(from_user="a", content="first", msg_id="1"))
    await started.wait()
    await asyncio.gather(
        loop._dispatch(IncomingMessage(from_user="a", content="second", msg_id="2")),
        loop._dispatch(IncomingMessage(from_user="b", content="other", msg_id="3")),
    )
    await asyncio.sleep(0)
    assert contexts["a"].metadata["_pending_user_messages"] == ["second"]
    assert "b" in contexts
    release.set()
    await asyncio.gather(*(entry["task"] for entry in list(loop._active_runs.values())))


@pytest.mark.asyncio
async def test_followup_race_during_attachment_download(tmp_path):
    entered, release, first_done = asyncio.Event(), asyncio.Event(), asyncio.Event()
    client = SimpleNamespace(download_media=AsyncMock())

    async def download(_):
        entered.set()
        await release.wait()
        return b"image data"

    client.download_media.side_effect = download
    loop = WeChatMessageLoop(client)
    calls = []

    async def handler(msg, active):
        calls.append(msg.msg_id)
        context = SimpleNamespace(workspace=tmp_path, metadata={"_accept_followups": True}, budget_exhausted=False)
        active.update(context=context)
        active["ready"].set()
        if msg.msg_id == "1":
            await first_done.wait()
            context.metadata["_accept_followups"] = False

    loop._default_handler = handler
    await loop._dispatch(IncomingMessage(from_user="a", content="first", msg_id="1"))
    await asyncio.sleep(0)
    followup = asyncio.create_task(
        loop._dispatch(IncomingMessage(from_user="a", msg_id="2", attachments=[MediaAttachment(media_type="image")]))
    )
    await entered.wait()
    first_done.set()
    await asyncio.sleep(0)
    release.set()
    await followup
    await asyncio.sleep(0)
    assert calls == ["1", "2"]


@pytest.mark.asyncio
async def test_attachment_followup_is_multimodal(tmp_path):
    release = asyncio.Event()
    client = SimpleNamespace(download_media=AsyncMock(return_value=b"image data"))
    loop = WeChatMessageLoop(client)
    context = SimpleNamespace(workspace=tmp_path, metadata={"_accept_followups": True}, budget_exhausted=False)

    async def handler(msg, active):
        active["context"] = context
        active["ready"].set()
        await release.wait()

    loop._default_handler = handler
    await loop._dispatch(IncomingMessage(from_user="a", content="first", msg_id="1"))
    await loop._dispatch(
        IncomingMessage(from_user="a", content="look", msg_id="2", attachments=[MediaAttachment(media_type="image")])
    )
    blocks = context.metadata["_pending_user_messages"][0]
    assert blocks[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert blocks[-1]["text"] == "look"
    assert len(list((tmp_path / "wechat_files").iterdir())) == 1
    release.set()
    await loop._active_runs["a"]["task"]

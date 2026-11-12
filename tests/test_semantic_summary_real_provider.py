"""Real-provider acceptance for the semantic summary chain.

Runs only when the local ~/.crabagent database has a Deepseek provider
configured; otherwise skipped. Verifies the real litellm call, the proxy
authorization binding, and that requests traverse a configured proxy.
"""
import asyncio
import json
import socket
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core import database as db
from sqlalchemy import select

from crabagent.core import provider_store
from crabagent.core.agent import background, background_group, semantic_summary
from crabagent.core.agent import agents
from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.tools.registry import ToolRegistry

HOME_DB = Path.home() / ".crabagent" / "crabagent.db"


def _real_deepseek():
    if not HOME_DB.exists():
        return None
    conn = sqlite3.connect(HOME_DB)
    try:
        row = conn.execute(
            "SELECT api_key, base_url FROM provider_configs WHERE name='Deepseek' AND enabled=1"
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return row


pytestmark = pytest.mark.skipif(_real_deepseek() is None, reason="no real Deepseek provider configured")


def make_context():
    ctx = AgentContext(workspace=Path("."), tool_registry=ToolRegistry(),
                       model="deepseek-chat", provider_name="Deepseek")
    ctx.metadata.update(user_id=1, session_id="session", branch_id="main")
    return ctx


async def _setup(monkeypatch, tmp_path, name, proxy_url=""):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}")
    async with engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, "async_session_factory", factory)
    monkeypatch.setattr(provider_store, "async_session_factory", factory)
    key_enc, base_url = _real_deepseek()
    extra = json.dumps({"proxy_enabled": True, "proxy_url": proxy_url}) if proxy_url else None
    async with db.async_session_factory() as conn:
        conn.add(db.ProviderConfig(name="Deepseek", display_name="Deepseek", provider_type="deepseek",
                                   api_key=provider_store.encrypt_api_key(provider_store.decrypt_api_key(key_enc)),
                                   base_url=base_url, enabled=1, is_default=1, extra=extra))
        conn.add(db.Conversation(session_id="session", user_id=1, active_branch="main"))
        await conn.commit()
    return engine


async def _run_group(monkeypatch):
    async def agent(_):
        return {"name": "a"}

    async def spawn(name, task, ctx, **kwargs):
        return agents.BackgroundAgentResult("succeeded", f"{task}: collected findings")
    monkeypatch.setattr(agents, "get_agent", agent)
    monkeypatch.setattr(agents, "spawn_sub_agent", spawn)
    steps = [{"id": "research", "agent_name": "a", "task": "survey"},
             {"id": "verify", "agent_name": "a", "task": "verify", "depends_on": ["research"]}]
    gid = await background_group.start(make_context(), steps)
    result = await background_group.wait(make_context(), gid, 30)
    assert result["status"] == "succeeded"
    return gid


async def _summarize(gid):
    _, identity = await semantic_summary.provider_binding(make_context())
    await semantic_summary.start(make_context(), gid,
                                 user_consented_to_external_processing=True,
                                 binding=identity["binding"])
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        status = await semantic_summary.get(make_context(), gid)
        if status["status"] in ("succeeded", "failed", "interrupted", "cancelled"):
            return status, identity
        await asyncio.sleep(0.5)
    raise TimeoutError(status)


class _ConnectProxy(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.seen = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.stopped = False

    def run(self):
        while not self.stopped:
            try:
                client, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()

    def _serve(self, client):
        upstream = None
        try:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = client.recv(4096)
                if not chunk:
                    return
                data += chunk
            head = data.decode("latin1", "replace")
            self.seen.append(head.split(" ")[1] if " " in head else "?")
            host, _, port = self.seen[-1].rpartition(":")
            import select
            upstream = socket.create_connection((host, int(port or 443)), timeout=20)
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            while True:
                readers, _, _ = select.select([client, upstream], [], [], 30)
                for r in readers:
                    chunk = r.recv(8192)
                    if not chunk:
                        return
                    (upstream if r is client else client).sendall(chunk)
        except Exception:
            pass
        finally:
            for s in (client, upstream):
                if s:
                    try:
                        s.close()
                    except Exception:
                        pass


@pytest.fixture(autouse=True)
async def _release_executor():
    yield
    from crabagent.core.agent import background_group as bg
    for job in list(bg._groups.values()):
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)
    for job in list(background._jobs.values()):
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)
    if background._watcher_task is not None and background._watcher_task.get_loop() is asyncio.get_running_loop():
        background._watcher_task.cancel()
        await asyncio.gather(background._watcher_task, return_exceptions=True)
    background._watcher_task = None
    if background._owner_file is not None:
        background._owner_file.close()
        background._owner_file = None
        background._owner_pid = None
    background._recovery_task = None
    background._reservations.clear()


async def test_real_provider_direct_and_proxy_chain(tmp_path, monkeypatch):
    proxy = _ConnectProxy()
    proxy.start()
    try:
        # Same network path as a regular chat: litellm/openai SDK honours the
        # environment proxy (provider-level `proxy` kwargs are ignored by
        # litellm - a pre-existing limitation shared with the main loop).
        monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{proxy.port}")
        engine = await _setup(monkeypatch, tmp_path, "proxied.db")
        gid = await _run_group(monkeypatch)
        status, identity = await _summarize(gid)
        assert status["status"] == "succeeded", status
        assert status["text"].strip()
        assert any("api.deepseek.com" in t for t in proxy.seen), proxy.seen
        # Provider configuration changes still require fresh consent.
        async with db.async_session_factory() as conn:
            provider = await conn.scalar(select(db.ProviderConfig).where(db.ProviderConfig.name == "Deepseek"))
            provider.api_key = provider_store.encrypt_api_key("rotated-key")
            await conn.commit()
        with pytest.raises(ValueError, match="Provider configuration changed"):
            await semantic_summary.start(make_context(), gid,
                                         user_consented_to_external_processing=True,
                                         binding=identity["binding"])
        await engine.dispose()
    finally:
        proxy.stopped = True
        proxy.sock.close()

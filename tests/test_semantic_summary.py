import asyncio
import json

import pytest
from sqlalchemy import select, update

from crabagent.core import database as db
from crabagent.core.agent import background, semantic_summary as semantic
from types import SimpleNamespace

from tests.test_background_delegation import context, session_factory  # noqa: F401


@pytest.fixture(autouse=True)
def bound_provider(monkeypatch):
    async def binding(context):
        return (SimpleNamespace(provider_type="openai"), ""), {"binding": "test-binding", "model": "test-model"}
    monkeypatch.setattr(semantic, "provider_binding", binding)


async def make_group(factory):
    async with factory() as conn:
        conn.add(db.BackgroundGroup(id="g", user_id=1, session_id="session", branch_id="main", status="succeeded"))
        conn.add(db.BackgroundGroupStep(group_id="g", step_id="a", agent_name="a", task="t", depends_on=[], allowed_tools=[], status="succeeded", result="original", job_id=""))
        await conn.commit()


async def test_consent_frozen_snapshot_and_conditional_write(session_factory, monkeypatch):
    await make_group(session_factory)
    entered, release = asyncio.Event(), asyncio.Event()
    async def complete(snapshot, *_):
        entered.set()
        await release.wait()
        assert json.loads(snapshot)["steps"][0]["result"] == "original"
        return "summary"
    monkeypatch.setattr(semantic, "_complete", complete)
    with pytest.raises(ValueError, match="consent"):
        await semantic.start(context(), "g", user_consented_to_external_processing=False, binding="test-binding")
    await semantic.start(context(), "g", user_consented_to_external_processing=True, binding="test-binding")
    await entered.wait()
    async with session_factory() as conn:
        await conn.execute(update(db.BackgroundGroupStep).values(result="changed"))
        await conn.commit()
    release.set()
    await semantic._jobs["g"]
    assert await semantic.get(context(), "g") == {"status": "succeeded", "text": "summary"}
    with pytest.raises(ValueError):
        await semantic.get(context(user=2), "g")


async def test_cancel_blocks_late_result_and_concurrent_cancel(session_factory, monkeypatch):
    await make_group(session_factory)
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def complete(*_):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaning.set()
            await release.wait()
            return "late"
    monkeypatch.setattr(semantic, "_complete", complete)
    await semantic.start(context(), "g", user_consented_to_external_processing=True, binding="test-binding")
    await entered.wait()
    a = asyncio.create_task(semantic.cancel(context(), "g"))
    await cleaning.wait()
    b = asyncio.create_task(semantic.cancel(context(), "g"))
    await asyncio.sleep(.05)
    release.set()
    assert (await a)["status"] == "cancelled"
    assert (await b)["status"] == "cancelled"
    assert (await semantic.get(context(), "g"))["text"] == ""


async def test_recovery_and_limits(session_factory):
    await make_group(session_factory)
    async with session_factory() as conn:
        conn.add(db.BackgroundSemanticSummary(group_id="g", status="running", snapshot="{}", text="", run_id="x"))
        await conn.commit()
    assert (await semantic.get(context(), "g"))["status"] == "interrupted"
    assert not await semantic._transition("g", "x", ("running",), status="succeeded", text="late")


async def test_no_tools_in_provider_call(session_factory, monkeypatch):
    import litellm
    captured = {}
    async def call(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="result"))])
    monkeypatch.setattr(litellm, "acompletion", call)
    provider = SimpleNamespace(provider_type="openai", api_key="key", base_url="https://example.com", extra={})
    assert await semantic._complete("{}", (provider, ""), "openai/test", "session") == "result"
    assert "tools" not in captured and "tool_choice" not in captured
    # Same path as the main loop: plain litellm params, no injected client.
    assert "client" not in captured
    assert captured["api_key"] == "key" and captured["api_base"] == "https://example.com"


async def test_oversize_snapshot_rejected(session_factory):
    await make_group(session_factory)
    async with session_factory() as conn:
        await conn.execute(update(db.BackgroundGroupStep).values(result="x" * semantic.MAX_SNAPSHOT_BYTES))
        await conn.commit()
    with pytest.raises(ValueError, match="byte limit"):
        await semantic.start(context(), "g", user_consented_to_external_processing=True, binding="test-binding")
    assert await semantic.get(context(), "g") is None


async def test_retry_blocks_stale_run(session_factory, monkeypatch):
    await make_group(session_factory)
    async with session_factory() as conn:
        conn.add(db.BackgroundSemanticSummary(group_id="g", status="interrupted", snapshot="{}", text="", run_id="old"))
        await conn.commit()
    async def complete(*args):
        return "new"
    monkeypatch.setattr(semantic, "_complete", complete)
    await semantic.start(context(), "g", user_consented_to_external_processing=True, binding="test-binding")
    job = semantic._jobs.get("g")
    if job:
        await job
    assert not await semantic._transition("g", "old", ("running", "pending"), status="succeeded", text="stale")
    assert (await semantic.get(context(), "g"))["text"] == "new"


async def test_binding_mismatch_rejected(session_factory):
    await make_group(session_factory)
    with pytest.raises(ValueError, match="configuration changed"):
        await semantic.start(context(), "g", user_consented_to_external_processing=True, binding="wrong")

async def test_real_binding_tracks_config_without_exposing_secrets(monkeypatch):
    from crabagent.core import provider_store
    from crabagent.core.agent import semantic_summary
    from dataclasses import replace
    # Restore the real function despite the default fixture.
    import importlib
    semantic_summary = importlib.reload(semantic_summary)
    provider = provider_store.ProviderInfo("p", "Provider", "openai", "secret", "https://user:pass@example.com/v1?key=secret", True, True, {})
    async def default(): return provider
    monkeypatch.setattr(provider_store, "get_default_provider", default)
    _, first = await semantic_summary.provider_binding(context())
    assert first["endpoint"] == "https://example.com/v1"
    assert "secret" not in str(first) and "pass" not in str(first)
    provider = replace(provider, api_key="changed")
    _, second = await semantic_summary.provider_binding(context())
    assert first["binding"] != second["binding"]


async def test_all_provider_types_allowed_at_binding(monkeypatch):
    import importlib
    from crabagent.core import provider_store
    real = importlib.reload(semantic)
    provider = provider_store.ProviderInfo("p", "P", "chatgpt", "", "", True, True, {})
    async def default(): return provider
    monkeypatch.setattr(provider_store, "get_default_provider", default)
    _, identity = await real.provider_binding(context())
    assert identity["model"].startswith("chatgpt/")
    from crabagent.core import proxy as proxy_mod
    async def no_proxy(_): return ""
    monkeypatch.setattr(proxy_mod, "resolve_llm_proxy", no_proxy)
    _, identity = await real.provider_binding(context())
    assert identity["endpoint"] == "provider default"


async def test_proxy_follows_global_config_binding_tracks_provider_only(session_factory, monkeypatch):
    import importlib
    import litellm
    from crabagent.core import provider_store, proxy
    real = importlib.reload(semantic)
    provider = provider_store.ProviderInfo("p", "P", "openai", "key", "https://example.com", True, True, {"proxy_enabled": True})
    route = {"url": "http://user:password@proxy.example:8080"}
    async def default(): return provider
    async def resolve(_): return route["url"]
    monkeypatch.setattr(provider_store, "get_default_provider", default)
    monkeypatch.setattr(proxy, "resolve_llm_proxy", resolve)
    frozen, first = await real.provider_binding(context())
    assert first["proxy"] == "http://proxy.example:8080"
    assert "password" not in str(first)
    route["url"] = "http://other:8080"
    _, second = await real.provider_binding(context())
    # Proxy changes follow global config and do NOT invalidate consent;
    # provider or model changes still do (binding excludes the proxy).
    assert first["binding"] == second["binding"]
    await make_group(session_factory)
    from dataclasses import replace
    changed = replace(provider, api_key="changed")
    async def default2(): return changed
    monkeypatch.setattr(provider_store, "get_default_provider", default2)
    with pytest.raises(ValueError, match="configuration changed"):
        await real.start(context(), "g", user_consented_to_external_processing=True, binding=first["binding"])
    monkeypatch.setattr(provider_store, "get_default_provider", default)
    captured = {}
    async def call(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])
    monkeypatch.setattr(litellm, "acompletion", call)
    assert await real._complete("{}", frozen, "openai/test", "session") == "ok"
    # The proxy travels through litellm params exactly like the main loop.
    assert captured["proxy"] == "http://other:8080"
    assert "client" not in captured


@pytest.mark.parametrize("status", ["succeeded", "failed", "interrupted", "cancelled"])
async def test_delete_terminal_summary_and_snapshot(session_factory, status):
    await make_group(session_factory)
    async with session_factory() as conn:
        conn.add(db.BackgroundSemanticSummary(group_id="g", status=status, snapshot="sensitive snapshot", text="private summary", run_id="old"))
        await conn.commit()
    with pytest.raises((LookupError, ValueError)):
        await semantic.delete(context(user=2), "g")
    assert await semantic.delete(context(), "g") is True
    assert await semantic.delete(context(), "g") is False
    assert not await semantic._transition("g", "old", ("running",), status="succeeded", text="late")
    async with session_factory() as conn:
        assert await conn.get(db.BackgroundSemanticSummary, "g") is None
        assert (await conn.get(db.BackgroundGroupStep, ("g", "a"))) is not None


@pytest.mark.parametrize("status", ["pending", "running", "cancelling"])
async def test_delete_rejects_active_summary(session_factory, status):
    await make_group(session_factory)
    async with session_factory() as conn:
        conn.add(db.BackgroundSemanticSummary(group_id="g", status=status, snapshot="secret", text="", run_id="x"))
        await conn.commit()
    with pytest.raises(ValueError):
        await semantic.delete(context(), "g")
    async with session_factory() as conn:
        assert (await conn.get(db.BackgroundSemanticSummary, "g")).snapshot == "secret"


async def test_delayed_old_cancel_does_not_cancel_retry(session_factory, monkeypatch):
    await make_group(session_factory)
    first_entered, fail_first = asyncio.Event(), asyncio.Event()
    second_entered, finish_second = asyncio.Event(), asyncio.Event()
    cancel_entered, release_cancel = asyncio.Event(), asyncio.Event()
    calls = 0

    async def complete(*_):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_entered.set()
            await fail_first.wait()
            raise RuntimeError("first run failed")
        second_entered.set()
        await finish_second.wait()
        return "retry result"

    original_transition = semantic._transition
    async def delayed_transition(*args, **kwargs):
        if kwargs.get("status") == "cancelling":
            cancel_entered.set()
            await release_cancel.wait()
        return await original_transition(*args, **kwargs)

    monkeypatch.setattr(semantic, "_complete", complete)
    monkeypatch.setattr(semantic, "_transition", delayed_transition)
    await semantic.start(context(), "g", user_consented_to_external_processing=True, binding="test-binding")
    await first_entered.wait()
    old_job = semantic._jobs["g"]
    cancel = asyncio.create_task(semantic.cancel(context(), "g"))
    await cancel_entered.wait()
    fail_first.set()
    await old_job
    await semantic.start(context(), "g", user_consented_to_external_processing=True, binding="test-binding")
    await second_entered.wait()
    new_job = semantic._jobs["g"]
    release_cancel.set()
    assert (await cancel)["status"] == "running"
    assert not new_job.done()
    finish_second.set()
    await new_job
    assert await semantic.get(context(), "g") == {"status": "succeeded", "text": "retry result"}

async def test_real_litellm_dispatch_hits_configured_endpoint(monkeypatch):
    import httpx
    from crabagent.core import provider_store
    seen = []
    original = httpx.AsyncClient
    async def handle(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 0,
            "model": "test", "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": "ok"}}]})
    class Client(original):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handle)
            super().__init__(*args, **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    provider = provider_store.ProviderInfo("p", "P", "openai", "key", "https://example.com/v1", True, True, {})
    assert await semantic._complete("{}", (provider, ""), "openai/test", "session") == "ok"
    assert seen == ["https://example.com/v1/chat/completions"]

async def test_cross_process_cancel_waits_for_cleanup(session_factory, tmp_path, monkeypatch):
    import sys
    await make_group(session_factory)
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def complete(*_):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
    monkeypatch.setattr(semantic, "_complete", complete)
    await semantic.start(context(), "g", user_consented_to_external_processing=True, binding="test-binding")
    await asyncio.wait_for(entered.wait(), 3)
    script = '''
import asyncio, sys
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from crabagent.core import database as db
from crabagent.core.agent import semantic_summary
from crabagent.core.agent.context import AgentContext
async def main():
    engine = create_async_engine("sqlite+aiosqlite:///" + sys.argv[1])
    db.async_session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ctx = AgentContext(workspace=Path("."))
    ctx.metadata.update(user_id=1, session_id="session", branch_id="main")
    print((await semantic_summary.cancel(ctx, "g"))["status"], flush=True)
    await engine.dispose()
asyncio.run(main())
'''
    proc = await asyncio.create_subprocess_exec(sys.executable, "-c", script, str(tmp_path / "test.db"),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await asyncio.wait_for(proc.communicate(), 15)
    assert proc.returncode == 0, stderr.decode()
    assert stdout.decode().strip() == "cancelling"
    await asyncio.wait_for(cleaning.wait(), 3)
    assert (await semantic.get(context(), "g"))["status"] == "cancelling"
    release.set()
    for _ in range(100):
        if (await semantic.get(context(), "g"))["status"] == "cancelled":
            break
        await asyncio.sleep(.05)
    assert (await semantic.get(context(), "g"))["status"] == "cancelled"


async def test_forwarded_summary_executed_by_owner_process(session_factory, tmp_path, monkeypatch):
    """A non-owner process forwards authorized summary starts to the owner."""
    import subprocess
    import sys
    from pathlib import Path
    database = tmp_path / "summary-forward.db"
    owner_ready = tmp_path / "owner.ready"

    code = '''
import asyncio, sys
from pathlib import Path
from types import SimpleNamespace
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from crabagent.core import database as db
from crabagent.core.agent import background
from crabagent.core.agent import semantic_summary as semantic


async def binding(context):
    return (SimpleNamespace(provider_type="openai"), ""), {"binding": "test-binding", "model": "test-model"}


async def complete(snapshot, *_):
    return "forwarded summary"


async def main():
    semantic.provider_binding = binding
    semantic._complete = complete
    engine = create_async_engine("sqlite+aiosqlite:///" + sys.argv[1])
    async with engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    db.async_session_factory = async_sessionmaker(engine, expire_on_commit=False)
    background._claim_executor()
    await background._ensure_executor()
    Path(sys.argv[2]).write_text("ready")
    await asyncio.sleep(30)


asyncio.run(main())
'''
    proc = subprocess.Popen([sys.executable, "-c", code, str(database), str(owner_ready)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(100):
            if owner_ready.exists():
                break
            await asyncio.sleep(0.05)
        assert owner_ready.exists(), "owner process did not start"

        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        engine2 = create_async_engine(f"sqlite+aiosqlite:///{database}")
        factory2 = async_sessionmaker(engine2, expire_on_commit=False)
        monkeypatch.setattr(db, "async_session_factory", factory2)
        async with factory2() as session:
            session.add(db.Conversation(session_id="session", user_id=1, active_branch="main"))
            session.add(db.BackgroundGroup(id="g", user_id=1, session_id="session", branch_id="main", status="succeeded"))
            session.add(db.BackgroundGroupStep(group_id="g", step_id="a", agent_name="a", task="t",
                                               depends_on=[], allowed_tools=[], status="succeeded",
                                               result="original", job_id=""))
            await session.commit()

        result = await semantic.start(context(), "g",
                                      user_consented_to_external_processing=True,
                                      binding="test-binding")
        assert result["status"] in ("pending", "running")
        deadline = asyncio.get_running_loop().time() + 15
        while asyncio.get_running_loop().time() < deadline:
            status = await semantic.get(context(), "g")
            if status["status"] in ("succeeded", "failed", "interrupted", "cancelled"):
                break
            await asyncio.sleep(0.1)
        assert status["status"] == "succeeded", status
        assert status["text"] == "forwarded summary"
        async with factory2() as conn:
            commands = (await conn.scalars(select(db.BackgroundStartCommand))).all()
        assert [c.status for c in commands] == ["done"]
        await engine2.dispose()
    finally:
        proc.kill()
        await asyncio.get_running_loop().run_in_executor(None, proc.wait)

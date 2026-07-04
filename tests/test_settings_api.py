from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from crabagent.serve.api import settings as settings_api


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeDB:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.added = []
        self.committed = False
        self.execute_calls = 0

    async def execute(self, statement):
        self.execute_calls += 1
        text = str(statement)
        if "WHERE app_settings.key =" in text:
            key = text.split("=")[-1].strip().strip(":key_1")
            # fallback to first matching row via simple scan on bound values not exposed in string
            return FakeResult([])
        return FakeResult(self.rows)

    def add(self, row):
        self.added.append(row)
        self.rows.append(row)

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_get_settings_returns_key_value_map():
    db = FakeDB([SimpleNamespace(key="default_model", value="gpt-4o"), SimpleNamespace(key="lang", value="zh-CN")])

    result = await settings_api.get_settings(user=SimpleNamespace(id=1), db=db)

    assert result == {"default_model": "gpt-4o", "lang": "zh-CN"}


@pytest.mark.asyncio
async def test_update_settings_updates_existing_and_inserts_new(monkeypatch: pytest.MonkeyPatch):
    existing = SimpleNamespace(key="default_model", value="gpt-4o")

    class UpdateDB(FakeDB):
        async def execute(self, statement):
            self.execute_calls += 1
            if self.execute_calls == 1:
                return FakeResult([existing])
            if self.execute_calls == 2:
                return FakeResult([])
            return FakeResult(self.rows)

    db = UpdateDB([existing])
    req = settings_api.UpdateSettingsRequest(settings={"default_model": "gpt-4.1", "theme": "paper"})

    result = await settings_api.update_settings(req, user=SimpleNamespace(id=1), db=db)

    assert existing.value == "gpt-4.1"
    assert any(getattr(row, "key", "") == "theme" for row in db.added)
    assert db.committed is True
    assert result["theme"] == "paper"


@pytest.mark.asyncio
async def test_test_searxng_success_uses_proxy(monkeypatch: pytest.MonkeyPatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [1, 2, 3]}

    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            captured["url"] = url
            return FakeResponse()

    monkeypatch.setitem(__import__("sys").modules, "httpx", SimpleNamespace(AsyncClient=FakeClient))
    monkeypatch.setattr("crabagent.core.proxy.resolve_category_proxy", _async_return("http://proxy:7890"))

    result = await settings_api.test_searxng(settings_api.TestSearxngRequest(url="https://sx.example"), user=SimpleNamespace(id=1))

    assert result == {"success": True, "result_count": 3}
    assert captured["proxy"] == "http://proxy:7890"
    assert captured["url"].startswith("https://sx.example/search")


@pytest.mark.asyncio
async def test_test_searxng_reports_failure_without_proxy(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            raise RuntimeError("searxng down")

    monkeypatch.setitem(__import__("sys").modules, "httpx", SimpleNamespace(AsyncClient=FakeClient))
    monkeypatch.setattr("crabagent.core.proxy.resolve_category_proxy", _async_return(None))

    result = await settings_api.test_searxng(settings_api.TestSearxngRequest(url="https://sx.example"), user=SimpleNamespace(id=1))

    assert result == {"success": False, "error": "searxng down"}
    assert "proxy" not in captured
    assert captured["timeout"] == 10.0


@pytest.mark.asyncio
async def test_test_proxy_reports_http_error(monkeypatch: pytest.MonkeyPatch):
    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            raise RuntimeError("connect failed")

    monkeypatch.setitem(__import__("sys").modules, "httpx", SimpleNamespace(AsyncClient=FakeClient))

    result = await settings_api.test_proxy(settings_api.TestProxyRequest(proxy="http://proxy:1"), user=SimpleNamespace(id=1))

    assert result["success"] is False
    assert "connect failed" in result["error"]


@pytest.mark.asyncio
async def test_test_proxy_rejects_empty_proxy(monkeypatch: pytest.MonkeyPatch):
    result = await settings_api.test_proxy(settings_api.TestProxyRequest(proxy=""), user=SimpleNamespace(id=1))

    assert result == {"success": False, "error": "Proxy URL is empty"}


@pytest.mark.asyncio
async def test_test_proxy_success_ignores_invalid_json(monkeypatch: pytest.MonkeyPatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("bad json")

    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            captured["url"] = url
            return FakeResponse()

    monkeypatch.setitem(__import__("sys").modules, "httpx", SimpleNamespace(AsyncClient=FakeClient))

    result = await settings_api.test_proxy(settings_api.TestProxyRequest(proxy="http://proxy:1"), user=SimpleNamespace(id=1))

    assert result["success"] is True
    assert result["ip"] == ""
    assert result["latency_ms"] >= 0
    assert captured["proxy"] == "http://proxy:1"
    assert captured["url"] == "https://httpbin.org/ip"


@pytest.mark.asyncio
async def test_get_skill_detail_raises_404_for_missing_skill(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(type(settings_api.app_settings), "skill_discovery_dirs", lambda self: [Path.cwd()])
    monkeypatch.setattr("crabagent.core.agent.skill.loader.discover_skills", lambda dirs: {})

    with pytest.raises(HTTPException) as exc:
        await settings_api.get_skill_detail("missing", user=SimpleNamespace(id=1))

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_skill_detail_returns_relative_and_absolute_aux_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    inside = skill_dir / "refs" / "a.md"
    outside = tmp_path / "shared.md"
    inside.parent.mkdir()
    inside.write_text("x", encoding="utf-8")
    outside.write_text("y", encoding="utf-8")
    skill = SimpleNamespace(
        name="demo",
        description="desc",
        content="body",
        location=skill_dir,
        auxiliary_files=[inside, outside],
    )
    monkeypatch.setattr(type(settings_api.app_settings), "skill_discovery_dirs", lambda self: [tmp_path])
    monkeypatch.setattr("crabagent.core.agent.skill.loader.discover_skills", lambda dirs: {"demo": skill})

    result = await settings_api.get_skill_detail("demo", user=SimpleNamespace(id=1))

    assert result["content"] == "body"
    assert result["auxiliary_files"] == ["refs/a.md", str(outside)]


@pytest.mark.asyncio
async def test_list_skills_formats_relative_aux_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    aux = skill_dir / "refs" / "a.md"
    aux.parent.mkdir()
    aux.write_text("x", encoding="utf-8")
    skill = SimpleNamespace(
        name="demo",
        description="desc",
        location=skill_dir,
        auxiliary_files=[aux],
    )
    monkeypatch.setattr(type(settings_api.app_settings), "skill_discovery_dirs", lambda self: [tmp_path])
    monkeypatch.setattr("crabagent.core.agent.skill.loader.discover_skills", lambda dirs: {"demo": skill})

    result = await settings_api.list_skills(user=SimpleNamespace(id=1))

    assert result[0]["auxiliary_files"] == ["refs/a.md"]


@pytest.mark.asyncio
async def test_list_skills_sorts_by_name(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    alpha_dir = tmp_path / "alpha"
    zebra_dir = tmp_path / "zebra"
    alpha_dir.mkdir()
    zebra_dir.mkdir()
    alpha = SimpleNamespace(name="alpha", description="a", location=alpha_dir, auxiliary_files=[])
    zebra = SimpleNamespace(name="zebra", description="z", location=zebra_dir, auxiliary_files=[])
    monkeypatch.setattr(type(settings_api.app_settings), "skill_discovery_dirs", lambda self: [tmp_path])
    monkeypatch.setattr("crabagent.core.agent.skill.loader.discover_skills", lambda dirs: {"zebra": zebra, "alpha": alpha})

    result = await settings_api.list_skills(user=SimpleNamespace(id=1))

    assert [item["name"] for item in result] == ["alpha", "zebra"]


def _async_return(value):
    async def inner(*args, **kwargs):
        return value

    return inner

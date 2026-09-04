from __future__ import annotations

from types import SimpleNamespace

import pytest

from crabagent.core.agent.tools import web as web_module


def test_format_results_empty():
    result = web_module._format_results("query", [], 5)
    assert "No results" in result


def test_format_results_truncates_to_limit():
    results = [{"title": f"T{i}", "url": f"http://x/{i}", "snippet": f"s{i}"} for i in range(10)]
    text = web_module._format_results("q", results, 3)

    assert "T0" in text
    assert "T2" in text
    assert "T3" not in text


def test_format_results_handles_missing_fields():
    text = web_module._format_results("q", [{"url": "https://example.com"}], 5)
    assert "example.com" in text


@pytest.mark.asyncio
async def test_search_searxng_builds_url_and_parses_results(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [{"title": "A", "url": "http://a", "content": "snippet A"}]}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return FakeResponse()

    monkeypatch.setitem(__import__("sys").modules, "httpx", SimpleNamespace(AsyncClient=FakeClient))
    monkeypatch.setattr("crabagent.core.proxy.resolve_category_proxy", _async_return(""))

    results = await web_module._search_searxng("hello world", 5, "https://sx.example")

    assert len(results) == 1
    assert results[0]["title"] == "A"
    assert captured["params"]["q"] == "hello world"
    assert captured["url"] == "https://sx.example/search"


@pytest.mark.asyncio
async def test_fetch_html_rejects_invalid_url():
    html, error = await web_module._fetch_html("file:///etc/passwd")

    assert html == ""
    assert "http:// or https://" in error


@pytest.mark.asyncio
async def test_fetch_html_returns_error_on_http_failure(monkeypatch: pytest.MonkeyPatch):
    import httpx

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr("crabagent.core.proxy.resolve_category_proxy", _async_return(""))

    html, error = await web_module._fetch_html("http://bad.test")

    assert html == ""
    assert "refused" in error


@pytest.mark.asyncio
async def test_web_search_falls_back_to_duckduckgo(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(web_module, "_get_setting", _async_return("https://sx.example"))

    async def failing_searxng(query, limit, url):
        raise RuntimeError("searxng down")

    async def fake_ddg(query, limit):
        return [{"title": "B", "url": "http://b", "snippet": "snippet B"}]

    monkeypatch.setattr(web_module, "_search_searxng", failing_searxng)
    monkeypatch.setattr(web_module, "_search_duckduckgo", fake_ddg)

    result = await web_module.web_search("hello", 3)

    assert "B" in result
    assert "snippet B" in result


@pytest.mark.asyncio
async def test_web_search_reports_provider_failure(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(web_module, "_get_setting", _async_return(None))

    async def failing_ddg(query, limit):
        raise RuntimeError("ddg down")

    monkeypatch.setattr(web_module, "_search_duckduckgo", failing_ddg)

    result = await web_module.web_search("hello", 3)

    assert "No results found" in result
    assert "DDGS: RuntimeError: ddg down" in result


@pytest.mark.asyncio
async def test_web_search_falls_back_when_searxng_returns_empty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(web_module, "_get_setting", _async_return("https://sx.example"))
    monkeypatch.setattr(web_module, "_search_searxng", _async_return([]))
    monkeypatch.setattr(
        web_module,
        "_search_duckduckgo",
        _async_return([{"title": "Fallback", "url": "https://example.com", "snippet": "ok"}]),
    )

    result = await web_module.web_search("hello", 50)

    assert "Fallback" in result


def test_normalize_results_filters_invalid_and_duplicate_urls():
    results = [
        {"title": "A", "url": "https://example.com", "snippet": "  hello\nworld  "},
        {"title": "duplicate", "url": "https://example.com"},
        {"title": "bad", "url": "javascript:alert(1)"},
    ]

    assert web_module._normalize_results(results, 5) == [
        {"title": "A", "url": "https://example.com", "snippet": "hello world"}
    ]


def test_scrapling_blocks_extracts_headings_and_lists():
    if not web_module.SCRAPLING_AVAILABLE:
        pytest.skip("scrapling not installed")

    html = '<div><h2>Title</h2><p>Text with <a href="/x">link</a></p><ul><li>item</li></ul></div>'
    from scrapling.parser import Selector

    page = Selector(html)
    blocks = web_module._scrapling_blocks(page)

    joined = "\n".join(blocks)
    assert "## Title" in joined
    assert "[link](/x)" in joined or "link" in joined
    assert "- item" in joined


def test_extract_with_scrapling_respects_css_selector():
    if not web_module.SCRAPLING_AVAILABLE:
        pytest.skip("scrapling not installed")

    html = "<html><head><title>Page</title></head><body><article><p>Main</p></article><aside>skip</aside></body></html>"
    result = web_module._extract_with_scrapling(html, "http://x", 5000, "article")

    assert "Main" in result
    assert "skip" not in result


def test_extract_with_lxml_truncates_and_formats_content():
    html = "<html><head><title>Page</title></head><body><h2>Head</h2><p>" + ("A" * 200) + "</p></body></html>"

    result = web_module._extract_with_lxml(html, "http://x", 80)

    assert result.startswith("# Page\nhttp://x")
    assert "## Head" in result
    assert "[truncated]" in result


@pytest.mark.asyncio
async def test_web_scrape_falls_back_to_lxml_when_scrapling_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(web_module, "SCRAPLING_AVAILABLE", True)
    monkeypatch.setattr(web_module, "_fetch_html", _async_return(("<html><body><p>fallback</p></body></html>", "")))
    monkeypatch.setattr(
        web_module, "_extract_with_scrapling", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setattr(web_module, "_extract_with_lxml", lambda html, url, max_length: "lxml fallback")

    result = await web_module.web_scrape("http://x", 50)

    assert result == "lxml fallback"


@pytest.mark.asyncio
async def test_web_scrape_returns_fetch_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(web_module, "_fetch_html", _async_return(("", "fetch failed")))

    result = await web_module.web_scrape("http://x", 50)

    assert result == "fetch failed"


def _async_return(value):
    async def inner(*args, **kwargs):
        return value

    return inner

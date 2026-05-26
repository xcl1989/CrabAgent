from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import quote_plus

from crabagent.core.agent.tools.registry import registry
from crabagent.core.config import settings

logger = logging.getLogger(__name__)


async def _get_setting(key: str) -> str | None:
    from sqlalchemy import select

    from crabagent.core.database import AppSetting, async_session_factory

    async with async_session_factory() as db:
        result = await db.execute(select(AppSetting).where(AppSetting.key == key))
        row = result.scalar_one_or_none()
        return row.value if row else None


def _format_results(query: str, results: list[dict], limit: int) -> str:
    results = results[:limit]
    if not results:
        return f'No results found for "{query}".'

    lines = [f'## Search results for "{query}"\n']
    for i, r in enumerate(results, 1):
        title = r.get("title", "Untitled")
        url = r.get("url", "")
        snippet = r.get("snippet", "").strip()
        lines.append(f"{i}. **{title}**\n   {url}")
        if snippet:
            lines.append(f"   {snippet}")
        lines.append("")

    return "\n".join(lines)


async def _search_searxng(query: str, limit: int, searxng_url: str) -> list[dict]:
    import httpx

    url = f"{searxng_url.rstrip('/')}/search?q={quote_plus(query)}&format=json&categories=general"
    client_kwargs = {"timeout": 15.0}
    if settings.web_proxy:
        client_kwargs["proxy"] = settings.web_proxy
    async with httpx.AsyncClient(**client_kwargs) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
        for r in data.get("results", [])
    ]


async def _search_duckduckgo(query: str, limit: int) -> list[dict]:
    import asyncio

    def _do_search():
        from ddgs import DDGS

        results = []
        t0 = time.time()
        kwargs = {}
        if settings.web_proxy:
            kwargs["proxy"] = settings.web_proxy
        ddgs = DDGS(**kwargs)
        try:
            it = ddgs.text(query, max_results=limit)
            for r in it:
                if time.time() - t0 > 18.0:
                    break
                results.append(
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    }
                )
        finally:
            try:
                ddgs.close()
            except Exception:
                pass
        return results

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_do_search), timeout=20.0
        )
    except TimeoutError:
        logger.info("DuckDuckGo search timed out for query: %s", query[:50])
        return []


@registry.register(
    name="web_search",
    description=(
        "Search the web. Returns a list of results with titles, URLs, "
        "and snippets. Uses SearXNG if configured, otherwise falls back "
        "to DuckDuckGo (no API key needed)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results. Default 5, max 10.",
                "default": 5,
            },
        },
        "required": ["query"],
    },
)
async def web_search(query: str, limit: int = 5) -> str:
    searxng_url = await _get_setting("searxng_url")

    if searxng_url:
        try:
            results = await _search_searxng(query, limit, searxng_url)
            return _format_results(query, results, limit)
        except Exception as e:
            logger.warning("SearXNG search failed, falling back to DuckDuckGo: %s", e)

    try:
        results = await _search_duckduckgo(query, limit)
        return _format_results(query, results, limit)
    except Exception as e:
        return f"Error searching: {e}"


@registry.register(
    name="web_scrape",
    description=(
        "Fetch and extract the main text content from a web page URL. Returns the page content in a readable format."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL of the web page to fetch.",
            },
            "max_length": {
                "type": "integer",
                "description": "Maximum length of the extracted text. Default: 10000.",
                "default": 10000,
            },
        },
        "required": ["url"],
    },
)
async def web_scrape(url: str, max_length: int = 10000) -> str:
    import httpx

    try:
        client_kwargs = {
            "timeout": 15.0,
            "follow_redirects": True,
            "headers": {
                "User-Agent": "Mozilla/5.0 (compatible; CrabAgent/1.0)",
                "Accept": "text/html,application/xhtml+xml",
            },
        }
        if settings.web_proxy:
            client_kwargs["proxy"] = settings.web_proxy
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text[:200000]
    except httpx.HTTPError as e:
        return f"Error fetching URL: {e}"

    try:
        from lxml import html as lxml_html

        tree = lxml_html.fromstring(html.encode("utf-8") if isinstance(html, str) else html)
    except Exception:
        return html[:max_length]

    for tag in tree.iter():
        if tag.tag in ("script", "style", "nav", "footer", "header", "aside", "noscript"):
            tag.getparent().remove(tag)

    parts: list[str] = []

    def extract_text(element: Any) -> None:
        if element.text:
            t = element.text.strip()
            if t:
                tag = element.tag if isinstance(element.tag, str) else ""
                if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                    level = int(tag[1])
                    parts.append(f"\n{'#' * level} {t}\n")
                elif tag == "li":
                    parts.append(f"- {t}")
                elif tag == "p":
                    parts.append(f"\n{t}\n")
                elif tag in ("td", "th"):
                    parts.append(f"{t} | ")
                else:
                    parts.append(t)
        for child in element:
            extract_text(child)
            if child.tail:
                t = child.tail.strip()
                if t:
                    parts.append(t)

    extract_text(tree)
    text = "\n".join(p for p in parts if p.strip())

    if len(text) > max_length:
        text = text[:max_length] + "\n\n... [truncated]"

    title = tree.findtext(".//title")
    header = f"# {title.strip()}\n{url}\n\n" if title else f"{url}\n\n"

    return header + text

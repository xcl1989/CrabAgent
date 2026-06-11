from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import quote_plus

from crabagent.core.agent.tools.registry import registry
from crabagent.core.config import settings

logger = logging.getLogger(__name__)

# ── Scrapling availability check (parser only, no fetchers) ──────────
SCRAPLING_AVAILABLE = False
try:
    from scrapling.parser import Selector

    SCRAPLING_AVAILABLE = True
except ImportError:
    Selector = None  # type: ignore[assignment,misc]


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
        return await asyncio.wait_for(asyncio.to_thread(_do_search), timeout=20.0)
    except TimeoutError:
        logger.info("DuckDuckGo search timed out for query: %s", query[:50])
        return []


# ── HTML fetching (shared by both paths) ─────────────────────────────


async def _fetch_html(url: str) -> tuple[str, str]:
    """Fetch HTML via httpx. Returns (html, error_msg)."""
    import httpx

    try:
        client_kwargs = {
            "timeout": 15.0,
            "follow_redirects": True,
            "headers": {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        }
        if settings.web_proxy:
            client_kwargs["proxy"] = settings.web_proxy
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text[:200000], ""
    except httpx.HTTPError as e:
        return "", f"Error fetching URL: {e}"


# ── Scrapling-based structured extraction ────────────────────────────

_SKIP_TAGS = frozenset([
    "script", "style", "nav", "footer", "header", "aside", "noscript",
    "iframe", "svg", "form", "button", "input", "select", "textarea",
])

_HEADING_TAGS = frozenset(["h1", "h2", "h3", "h4", "h5", "h6"])

_BLOCK_TAGS = frozenset([
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "tr",
    "blockquote", "pre", "code", "dd", "dt",
])


def _scrapling_blocks(el: Any, depth: int = 0) -> list[str]:
    """Recursively extract text blocks from a Scrapling Selector tree.

    Strategy: block-level elements (p, h1-h6, li, tr, …) are leaf nodes
    whose *full* text (including inline children like <a>) is captured via
    ``get_all_text()``.  Container elements (div, section, …) are recursed
    into.  Elements in ``_SKIP_TAGS`` are silently ignored.
    """
    tag = el.tag if isinstance(getattr(el, "tag", None), str) else ""
    if tag in _SKIP_TAGS:
        return []

    # ── Block-level element → grab its complete text ──────────────
    if tag in _BLOCK_TAGS:
        full = el.get_all_text().strip()
        if not full:
            return []
        if tag in _HEADING_TAGS:
            level = int(tag[1])
            return [f"{'#' * level} {full}"]
        if tag == "li":
            return [f"- {full}"]
        if tag == "tr":
            cells = [
                td.get_all_text().strip()
                for td in el.css("td,th")
                if td.get_all_text().strip()
            ]
            return [f"| {' | '.join(cells)} |"] if cells else []
        # p, blockquote, pre, … — process inline links
        return [_scrapling_inline(el)]

    # ── Container element → recurse into children ─────────────────
    blocks: list[str] = []
    children = list(el.children) if hasattr(el, "children") else []
    if not children:
        text = el.get_all_text().strip()
        if text and depth < 2:
            blocks.append(text)
    else:
        for child in children:
            blocks.extend(_scrapling_blocks(child, depth + 1))
    return blocks


def _scrapling_inline(el: Any) -> str:
    """Convert inline elements inside a block (e.g. <p>) to Markdown text.

    Replaces ``<a>`` tags with ``[text](href)`` and preserves surrounding
    text by using the parent's direct ``.text`` plus child ``.tail``-like
    content via ``get_all_text()``.
    """
    html_content = el.html_content
    if "<a " not in html_content:
        return el.get_all_text().strip()

    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in (el.children if hasattr(el, "children") else []):
        if isinstance(getattr(child, "tag", None), str) and child.tag == "a":
            href = child.attrib.get("href", "")
            link_text = child.get_all_text().strip()
            if href and link_text:
                parts.append(f"[{link_text}]({href})")
            elif link_text:
                parts.append(link_text)
        else:
            t = child.get_all_text().strip()
            if t:
                parts.append(t)
    return "".join(parts).strip()


def _extract_with_scrapling(html: str, url: str, max_length: int, css_selector: str | None) -> str:
    """Parse HTML with Scrapling Selector for high-quality structured extraction."""
    page = Selector(html)

    # Title
    title_el = page.css("title::text").get()
    title = title_el.strip() if title_el else ""

    # If user specified a CSS selector, extract only matching elements
    if css_selector:
        elements = page.css(css_selector)
        if not elements:
            return f"{url}\n\nNo elements matched selector: {css_selector}"
        parts: list[str] = []
        for el in elements:
            text = el.get_all_text() if hasattr(el, "get_all_text") else (el.text or "")
            if text and text.strip():
                parts.append(text.strip())
        header = f"# {title}\n{url}\n\n" if title else f"{url}\n\n"
        body = "\n\n".join(parts)
        if len(body) > max_length:
            body = body[:max_length] + "\n\n... [truncated]"
        return header + body

    # Full page extraction — prefer main/article, fall back to body
    main = page.css("main")
    if not main:
        main = page.css("article")
    root = main[0] if main else page

    blocks = _scrapling_blocks(root)
    body = "\n\n".join(blocks)
    if len(body) > max_length:
        body = body[:max_length] + "\n\n... [truncated]"

    header = f"# {title}\n{url}\n\n" if title else f"{url}\n\n"
    return header + body


# ── Legacy lxml-based extraction (fallback) ──────────────────────────


def _extract_with_lxml(html: str, url: str, max_length: int) -> str:
    """Original lxml-based extraction — kept as fallback when Scrapling is unavailable."""
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


# ── Tool registrations ───────────────────────────────────────────────


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
        "Fetch and extract the main text content from a web page URL. "
        "Returns the page content in a readable format with structure preserved "
        "(headings, lists, tables, links). Optionally extract only elements matching "
        "a CSS selector."
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
            "selector": {
                "type": "string",
                "description": "Optional CSS selector to extract specific elements instead of the full page. "
                'E.g. "article", ".product-card", "#main-content".',
            },
        },
        "required": ["url"],
    },
)
async def web_scrape(url: str, max_length: int = 10000, selector: str | None = None) -> str:
    # 1. Fetch HTML
    html, error = await _fetch_html(url)
    if error:
        return error

    # 2. Parse with Scrapling (preferred) or lxml (fallback)
    if SCRAPLING_AVAILABLE:
        try:
            return _extract_with_scrapling(html, url, max_length, selector)
        except Exception as e:
            logger.warning("Scrapling parsing failed, falling back to lxml: %s", e)

    # selector param not supported in lxml fallback — extract full page
    return _extract_with_lxml(html, url, max_length)

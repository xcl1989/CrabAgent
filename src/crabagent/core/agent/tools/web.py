from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urlparse

from crabagent.core.agent.tools.registry import registry

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


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_results(results: list[dict], limit: int) -> list[dict]:
    normalized: list[dict] = []
    seen: set[str] = set()
    for result in results:
        url = _clean_text(result.get("url") or result.get("href"))
        if not url or url in seen:
            continue
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        seen.add(url)
        normalized.append(
            {
                "title": _clean_text(result.get("title")) or parsed.netloc,
                "url": url,
                "snippet": _clean_text(result.get("snippet") or result.get("content") or result.get("body")),
            }
        )
        if len(normalized) >= limit:
            break
    return normalized


def _format_results(query: str, results: list[dict], limit: int) -> str:
    results = _normalize_results(results, limit)
    if not results:
        return f'No results found for "{query}".'

    lines = [f'## Search results for "{query}"\n']
    for i, result in enumerate(results, 1):
        lines.append(f"{i}. **{result['title']}**\n   {result['url']}")
        if result["snippet"]:
            lines.append(f"   {result['snippet']}")
        lines.append("")

    return "\n".join(lines)


async def _search_searxng(query: str, limit: int, searxng_url: str) -> list[dict]:
    import httpx

    from crabagent.core.proxy import resolve_category_proxy

    client_kwargs: dict[str, Any] = {"timeout": 15.0, "follow_redirects": True}
    proxy = await resolve_category_proxy("web")
    if proxy:
        client_kwargs["proxy"] = proxy
    async with httpx.AsyncClient(**client_kwargs) as client:
        resp = await client.get(
            f"{searxng_url.rstrip('/')}/search",
            params={"q": query, "format": "json", "categories": "general", "language": "auto"},
            headers={"Accept": "application/json", "User-Agent": "CrabAgent/1.0"},
        )
        resp.raise_for_status()
        data = resp.json()

    return _normalize_results(data.get("results", []), limit)


async def _search_duckduckgo(query: str, limit: int) -> list[dict]:
    from crabagent.core.proxy import resolve_category_proxy

    proxy = await resolve_category_proxy("web")

    def _do_search() -> list[dict]:
        from ddgs import DDGS

        kwargs = {"timeout": 8}
        if proxy:
            kwargs["proxy"] = proxy
        ddgs = DDGS(**kwargs)
        try:
            # Request extra candidates so invalid and duplicate URLs do not consume the limit.
            raw_results = ddgs.text(query, max_results=min(limit * 2, 20), backend="auto")
            return _normalize_results(list(raw_results or []), limit)
        finally:
            try:
                ddgs.close()
            except Exception:
                pass

    try:
        return await asyncio.wait_for(asyncio.to_thread(_do_search), timeout=20.0)
    except TimeoutError:
        logger.info("DDGS search timed out for query: %s", query[:50])
        return []


# ── HTML fetching (shared by both paths) ─────────────────────────────


async def _fetch_html(url: str) -> tuple[str, str]:
    """Fetch a bounded HTML response. Returns (html, error_msg)."""
    import httpx

    from crabagent.core.proxy import resolve_category_proxy

    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "", "Error fetching URL: only valid http:// or https:// URLs are supported."

    try:
        client_kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(20.0, connect=7.0),
            "follow_redirects": True,
            "headers": {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
                "Accept-Encoding": "gzip, deflate",
            },
        }
        proxy = await resolve_category_proxy("web")
        if proxy:
            client_kwargs["proxy"] = proxy
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(url.strip())
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "").lower()
            if content_type and not any(kind in content_type for kind in ("text/", "html", "xml", "json")):
                return "", f"Error fetching URL: unsupported content type {content_type}."
            return resp.text[:500_000], ""
    except httpx.HTTPError as e:
        return "", f"Error fetching URL: {type(e).__name__}: {e}"
    except Exception as e:
        logger.exception("Unexpected web fetch failure for %s", url)
        return "", f"Error fetching URL: {type(e).__name__}: {e}"


# ── Scrapling-based structured extraction ────────────────────────────

_SKIP_TAGS = frozenset(
    [
        "script",
        "style",
        "nav",
        "footer",
        "header",
        "aside",
        "noscript",
        "iframe",
        "svg",
        "form",
        "button",
        "input",
        "select",
        "textarea",
    ]
)

_HEADING_TAGS = frozenset(["h1", "h2", "h3", "h4", "h5", "h6"])

_BLOCK_TAGS = frozenset(
    [
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "li",
        "tr",
        "blockquote",
        "pre",
        "code",
        "dd",
        "dt",
    ]
)


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
            cells = [td.get_all_text().strip() for td in el.css("td,th") if td.get_all_text().strip()]
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
    for child in el.children if hasattr(el, "children") else []:
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
    query = query.strip()
    if not query:
        return "Error searching: query must not be empty."
    limit = max(1, min(limit, 10))
    errors: list[str] = []
    searxng_url = await _get_setting("searxng_url")

    if searxng_url:
        try:
            results = await _search_searxng(query, limit, searxng_url)
            if results:
                return _format_results(query, results, limit)
            errors.append("SearXNG returned no results")
        except Exception as e:
            errors.append(f"SearXNG: {type(e).__name__}: {e}")
            logger.warning("SearXNG search failed, falling back to DDGS: %s", e)

    try:
        results = await _search_duckduckgo(query, limit)
        if results:
            return _format_results(query, results, limit)
        errors.append("DDGS returned no results")
    except Exception as e:
        errors.append(f"DDGS: {type(e).__name__}: {e}")
        logger.warning("DDGS search failed for %s: %s", query[:50], e)

    detail = "; ".join(errors)
    return f'No results found for "{query}". Search providers failed or returned no usable results. {detail}'


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
    max_length = max(100, min(max_length, 100_000))
    selector = selector.strip() if selector else None

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

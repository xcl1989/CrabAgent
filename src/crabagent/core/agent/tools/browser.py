from __future__ import annotations

import base64
import hashlib
import logging
import os
import tempfile
from typing import Any

from crabagent.core.agent.tools.browser_dom import (
    find_element_by_index,
    format_elements_for_llm,
    label_page_elements,
)
from crabagent.core.agent.tools.registry import registry

logger = logging.getLogger(__name__)

PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.async_api import Browser, BrowserContext, Page, async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_vision_model_context(context: Any) -> bool:
    if context is None:
        return False
    model = getattr(context, "model", None) or ""
    if not model:
        model = context.metadata.get("_resolved_model", "") if hasattr(context, "metadata") else ""
    if not model:
        return False
    try:
        from crabagent.core.agent.token_limits import is_vision_model

        return bool(is_vision_model(model))
    except Exception:
        return False


def _read_screenshot_as_data_url(path: str, max_bytes: int = 200_000) -> str:
    """Read a saved screenshot file and return a base64 data URL.

    If the file is larger than ``max_bytes``, returns an empty string (the
    caller will fall back to text-only). This prevents giant screenshots from
    blowing up the LLM context window.
    """

    if not path or not os.path.exists(path):
        return ""
    try:
        size = os.path.getsize(path)
        if size > max_bytes:
            logger.debug("screenshot %s skipped: %d bytes > %d", path, size, max_bytes)
            return ""
        with open(path, "rb") as f:
            data = f.read()
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception:
        return ""


def _build_browser_result(
    text_body: str,
    screenshot_path: str,
    *,
    context: Any = None,
    dom_section: str = "",
) -> str | list[dict]:
    """Construct the final tool result, possibly with image_url blocks.

    - Non-vision model → plain string, with optional DOM section + a hint
      pointing to the saved screenshot path.
    - Vision model → list-of-blocks: text + image_url + DOM. The screenshot is
      embedded as a base64 data URL.
    """

    parts: list[str] = []
    if dom_section:
        parts.append(dom_section)
    parts.append(text_body)
    text = "\n\n".join(p for p in parts if p).strip()

    if not _is_vision_model_context(context):
        if screenshot_path:
            text += f"\n\n[Screenshot saved at: {screenshot_path} — visible in Web UI]"
        return text

    blocks: list[dict] = [{"type": "text", "text": text}]
    if screenshot_path:
        data_url = _read_screenshot_as_data_url(screenshot_path)
        if data_url:
            blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": data_url},
                    "file_path": screenshot_path,
                    "mime": "image/png",
                }
            )
        else:
            blocks.append(
                {
                    "type": "text",
                    "text": f"\n[Screenshot saved at: {screenshot_path} — too large to embed]",
                }
            )
    return blocks


# ---------------------------------------------------------------------------
# BrowserManager
# ---------------------------------------------------------------------------


class BrowserManager:
    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._headless = os.environ.get("CRAB_BROWSER_HEADLESS", "true").lower() == "true"
        # Rolling history of recent screenshots (for context-aware models)
        self._screenshot_history: list[dict[str, Any]] = []
        try:
            from crabagent.core.config import settings

            self._history_max = int(getattr(settings, "browser_screenshot_history", 3))
        except Exception:
            self._history_max = 3

    @property
    def is_running(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    @property
    def page(self) -> Page | None:
        return self._page

    async def ensure_started(self) -> None:
        if self.is_running:
            return
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "playwright is not installed. "
                "Install with: pip install 'crabagent[browser]' && playwright install chromium"
            )
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        self._page = await self._context.new_page()

    # --- core ops -----------------------------------------------------------

    async def navigate(self, url: str, wait_until: str = "domcontentloaded") -> dict[str, Any]:
        await self.ensure_started()
        response = await self._page.goto(url, wait_until=wait_until, timeout=30000)
        title = await self._page.title()
        status = response.status if response else None
        content = await self._extract_text(max_length=3000)
        screenshot_path = await self._take_screenshot()
        # Label interactive elements AFTER screenshot so the data-crab-idx
        # attribute does not bleed into the visual snapshot.
        elements = await label_page_elements(self._page)
        return {
            "url": self._page.url,
            "title": title,
            "status": status,
            "content_preview": content,
            "screenshot": screenshot_path,
            "elements": elements,
        }

    async def click(self, selector: str, text: str | None = None) -> dict[str, Any]:
        await self.ensure_started()
        if text and not selector:
            selector = f"text={text}"
        await self._page.click(selector, timeout=10000)
        await self._page.wait_for_load_state("domcontentloaded", timeout=10000)
        title = await self._page.title()
        content = await self._extract_text(max_length=2000)
        screenshot_path = await self._take_screenshot()
        # Re-label after navigation since DOM may have changed
        elements = await label_page_elements(self._page)
        return {
            "clicked": selector or text,
            "url": self._page.url,
            "title": title,
            "content_preview": content,
            "screenshot": screenshot_path,
            "elements": elements,
        }

    async def click_index(self, index: int) -> dict[str, Any]:
        await self.ensure_started()
        element = find_element_by_index(self._page, index)
        if not element:
            return {
                "error": (
                    f"Invalid index {index}. Call browser_navigate first, or use a value from the most recent [N] list."
                ),
                "available": [el.get("idx") for el in self._get_cached_elements()],
            }
        selector = element.get("selector", "")
        if not selector:
            return {"error": f"Element [{index}] has no usable selector."}
        try:
            await self._page.click(selector, timeout=10000)
            await self._page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception as exc:
            return {"error": f"Click on [{index}] ({selector}) failed: {exc}"}
        title = await self._page.title()
        content = await self._extract_text(max_length=2000)
        screenshot_path = await self._take_screenshot()
        elements = await label_page_elements(self._page)
        return {
            "clicked_index": index,
            "clicked_selector": selector,
            "url": self._page.url,
            "title": title,
            "content_preview": content,
            "screenshot": screenshot_path,
            "elements": elements,
        }

    async def type_text(self, selector: str, text: str, submit: bool = False) -> dict[str, Any]:
        await self.ensure_started()
        await self._page.fill(selector, "")
        await self._page.type(selector, text, delay=50)
        if submit:
            await self._page.keyboard.press("Enter")
            await self._page.wait_for_load_state("domcontentloaded", timeout=10000)
        title = await self._page.title()
        content = await self._extract_text(max_length=2000)
        screenshot_path = await self._take_screenshot()
        elements = await label_page_elements(self._page)
        return {
            "typed_in": selector,
            "url": self._page.url,
            "title": title,
            "content_preview": content,
            "screenshot": screenshot_path,
            "elements": elements,
        }

    async def screenshot(self, full_page: bool = False) -> dict[str, Any]:
        await self.ensure_started()
        path = await self._take_screenshot(full_page=full_page)
        return {"screenshot": path, "url": self._page.url, "title": await self._page.title()}

    async def extract(self, selector: str | None = None, max_length: int = 10000) -> dict[str, Any]:
        await self.ensure_started()
        content = await self._extract_text(selector=selector, max_length=max_length)
        return {"url": self._page.url, "title": await self._page.title(), "content": content}

    async def scroll(self, direction: str = "down", amount: int = 500) -> dict[str, Any]:
        await self.ensure_started()
        delta = amount if direction == "down" else -amount
        await self._page.mouse.wheel(0, delta)
        await self._page.wait_for_timeout(500)
        screenshot_path = await self._take_screenshot()
        elements = await label_page_elements(self._page)
        return {
            "scrolled": direction,
            "amount": amount,
            "url": self._page.url,
            "screenshot": screenshot_path,
            "elements": elements,
        }

    async def close(self) -> None:
        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._screenshot_history.clear()

    # --- private helpers ---------------------------------------------------

    def _get_cached_elements(self) -> list[dict[str, Any]]:
        if not self._page:
            return []
        from crabagent.core.agent.tools.browser_dom import get_label_cache

        return get_label_cache(self._page)

    async def _extract_text(self, selector: str | None = None, max_length: int = 10000) -> str:
        if not self._page:
            return ""
        try:
            if selector:
                el = await self._page.query_selector(selector)
                if not el:
                    return f"Element not found: {selector}"
                text = await el.inner_text()
            else:
                text = await self._page.inner_text("body")
        except Exception as e:
            return f"Error extracting text: {e}"

        text = text.strip()
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        text = "\n".join(lines)
        if len(text) > max_length:
            text = text[:max_length] + "\n\n... [truncated]"
        return text

    async def _take_screenshot(self, full_page: bool = False) -> str:
        if not self._page:
            return ""
        ss_dir = os.path.join(tempfile.gettempdir(), "crabagent_screenshots")
        os.makedirs(ss_dir, exist_ok=True)
        url_hash = hashlib.md5(self._page.url.encode()).hexdigest()[:12]
        ts = hashlib.md5(str(os.getpid()).encode()).hexdigest()[:6]
        filename = f"{url_hash}_{ts}.png"
        path = os.path.join(ss_dir, filename)
        try:
            clip = None if full_page else {"x": 0, "y": 0, "width": 1280, "height": 800}
            await self._page.screenshot(path=path, full_page=full_page, clip=clip)
        except Exception as exc:
            logger.debug("screenshot failed: %s", exc)
            return ""
        # Track in rolling history
        title = ""
        try:
            title = await self._page.title()
        except Exception:
            pass
        self._push_history(path, title)
        return path

    def _push_history(self, path: str, title: str) -> None:
        self._screenshot_history.append({"path": path, "title": title})
        if len(self._screenshot_history) > self._history_max:
            self._screenshot_history.pop(0)

    def get_screenshot_history(self) -> list[dict[str, Any]]:
        return list(self._screenshot_history)


def _get_browser_manager(context: Any) -> BrowserManager | None:
    if context is None:
        return None
    bm = context.metadata.get("_browser_manager")
    if bm is None:
        bm = BrowserManager()
        context.metadata["_browser_manager"] = bm
    return bm


# ---------------------------------------------------------------------------
# Tool registrations
# ---------------------------------------------------------------------------


def _format_dom_section(elements: list[dict[str, Any]]) -> str:
    if not elements:
        return ""
    return "## Interactive Elements (use browser_click_index)\n" + format_elements_for_llm(elements)


def _make_text_body(fields: dict[str, Any], extra: str = "") -> str:
    lines: list[str] = []
    for key, label in [
        ("clicked", "**Clicked:**"),
        ("clicked_index", "**Clicked index:**"),
        ("clicked_selector", "**Selector:**"),
        ("typed_in", "**Typed into:**"),
    ]:
        if fields.get(key):
            lines.append(f"{label} {fields[key]}")
    for key, label in [
        ("url", "**URL:**"),
        ("title", "**Title:**"),
        ("status", "**Status:**"),
    ]:
        if fields.get(key) is not None:
            lines.append(f"{label} {fields[key]}")
    if extra:
        lines.append(extra)
    if fields.get("content_preview"):
        lines.append("")
        lines.append(fields["content_preview"])
    return "\n".join(lines).strip()


if PLAYWRIGHT_AVAILABLE:

    @registry.register(
        name="browser_navigate",
        description=(
            "Navigate to a URL in a headless browser. Returns page title, URL, content "
            "preview, a screenshot, and a numbered list of interactive elements. Use "
            "browser_click_index(index=N) to click element [N] from the list — this is "
            "much more reliable than guessing CSS selectors."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to navigate to."},
                "wait_until": {
                    "type": "string",
                    "description": (
                        "When to consider navigation complete. "
                        "Options: 'domcontentloaded', 'load', 'networkidle'. Default: 'domcontentloaded'."
                    ),
                    "default": "domcontentloaded",
                },
            },
            "required": ["url"],
        },
        requires_permission=True,
        metadata={"source": "builtin", "category": "browser"},
    )
    async def browser_navigate(url: str, wait_until: str = "domcontentloaded", context=None) -> str | list:
        bm = _get_browser_manager(context)
        if not bm:
            return "Error: browser not available"
        try:
            result = await bm.navigate(url, wait_until=wait_until)
            body = _make_text_body(result)
            dom = _format_dom_section(result.get("elements") or [])
            return _build_browser_result(
                body,
                result.get("screenshot", ""),
                context=context,
                dom_section=dom,
            )
        except Exception as e:
            return f"Error navigating to {url}: {e}"

    @registry.register(
        name="browser_click",
        description=(
            "Click an element on the current page. Prefer browser_click_index after a "
            "browser_navigate — only fall back to this tool when you already know the "
            "exact selector. Use either selector OR text."
        ),
        parameters={
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector of the element to click (e.g., '#submit-btn', 'a.login').",
                },
                "text": {
                    "type": "string",
                    "description": "Visible text of the element to click (alternative to selector).",
                },
            },
        },
        requires_permission=True,
        metadata={"source": "builtin", "category": "browser"},
    )
    async def browser_click(selector: str | None = None, text: str | None = None, context=None) -> str | list:
        bm = _get_browser_manager(context)
        if not bm:
            return "Error: browser not available"
        if not selector and not text:
            return "Error: provide either 'selector' or 'text'"
        try:
            result = await bm.click(selector=selector or "", text=text)
            if "error" in result:
                return f"Error: {result['error']}"
            body = _make_text_body(result)
            dom = _format_dom_section(result.get("elements") or [])
            return _build_browser_result(
                body,
                result.get("screenshot", ""),
                context=context,
                dom_section=dom,
            )
        except Exception as e:
            return f"Error clicking element: {e}"

    @registry.register(
        name="browser_click_index",
        description=(
            "Click an interactive element by its numbered index from the most recent "
            "browser_navigate / browser_click / browser_type call. The index corresponds "
            "to the [N] labels shown in the 'Interactive Elements' section of the previous "
            "tool result. This is the recommended way to click — it is faster and more "
            "reliable than guessing CSS selectors."
        ),
        parameters={
            "type": "object",
            "properties": {
                "index": {
                    "type": "integer",
                    "description": "1-based index from the [N] list in the previous browser tool result.",
                },
            },
            "required": ["index"],
        },
        requires_permission=True,
        metadata={"source": "builtin", "category": "browser"},
    )
    async def browser_click_index(index: int, context=None) -> str | list:
        bm = _get_browser_manager(context)
        if not bm:
            return "Error: browser not available"
        if not bm.is_running:
            return "Error: no active browser session. Use browser_navigate first."
        try:
            result = await bm.click_index(index)
            if result.get("error"):
                available = result.get("available") or []
                avail_hint = ""
                if available:
                    sample = available[:20]
                    avail_hint = f"\n\nAvailable indices: {sample}{' ...' if len(available) > 20 else ''}"
                return f"Error: {result['error']}{avail_hint}"
            body = _make_text_body(result)
            dom = _format_dom_section(result.get("elements") or [])
            return _build_browser_result(
                body,
                result.get("screenshot", ""),
                context=context,
                dom_section=dom,
            )
        except Exception as e:
            return f"Error clicking index {index}: {e}"

    @registry.register(
        name="browser_type",
        description=(
            "Type text into an input field. After typing, the page is re-labelled so the "
            "next browser_click_index call uses fresh [N] indices."
        ),
        parameters={
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector of the input field (e.g., '#search', 'input[name=\"q\"]').",
                },
                "text": {"type": "string", "description": "The text to type into the field."},
                "submit": {
                    "type": "boolean",
                    "description": "Whether to press Enter after typing to submit the form. Default: false.",
                    "default": False,
                },
            },
            "required": ["selector", "text"],
        },
        requires_permission=True,
        metadata={"source": "builtin", "category": "browser"},
    )
    async def browser_type(selector: str, text: str, submit: bool = False, context=None) -> str | list:
        bm = _get_browser_manager(context)
        if not bm:
            return "Error: browser not available"
        try:
            result = await bm.type_text(selector, text, submit=submit)
            body = _make_text_body(result)
            dom = _format_dom_section(result.get("elements") or [])
            return _build_browser_result(
                body,
                result.get("screenshot", ""),
                context=context,
                dom_section=dom,
            )
        except Exception as e:
            return f"Error typing text: {e}"

    @registry.register(
        name="browser_screenshot",
        description=(
            "Take a screenshot of the current page. Returns the file path; for vision "
            "models the image is embedded directly into the conversation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "full_page": {
                    "type": "boolean",
                    "description": "Whether to capture the full scrollable page. Default: false.",
                    "default": False,
                },
            },
        },
        metadata={"source": "builtin", "category": "browser"},
    )
    async def browser_screenshot(full_page: bool = False, context=None) -> str | list:
        bm = _get_browser_manager(context)
        if not bm:
            return "Error: browser not available"
        if not bm.is_running:
            return "Error: no active browser session. Use browser_navigate first."
        try:
            result = await bm.screenshot(full_page=full_page)
            body = f"**URL:** {result['url']}\n**Title:** {result['title']}"
            return _build_browser_result(body, result.get("screenshot", ""), context=context)
        except Exception as e:
            return f"Error taking screenshot: {e}"

    @registry.register(
        name="browser_extract",
        description="Extract text content from the current page (optionally a specific element).",
        parameters={
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector. If omitted, extracts from the full page body.",
                },
                "max_length": {
                    "type": "integer",
                    "description": "Maximum length of extracted text. Default: 10000.",
                    "default": 10000,
                },
            },
        },
        metadata={"source": "builtin", "category": "browser"},
    )
    async def browser_extract(selector: str | None = None, max_length: int = 10000, context=None) -> str:
        bm = _get_browser_manager(context)
        if not bm:
            return "Error: browser not available"
        if not bm.is_running:
            return "Error: no active browser session. Use browser_navigate first."
        try:
            result = await bm.extract(selector=selector, max_length=max_length)
            header = f"**URL:** {result['url']}\n**Title:** {result['title']}\n\n"
            return header + result["content"]
        except Exception as e:
            return f"Error extracting content: {e}"

    @registry.register(
        name="browser_scroll",
        description="Scroll the current page up or down. Re-labels interactive elements after scrolling.",
        parameters={
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "description": "Direction to scroll: 'up' or 'down'. Default: 'down'.",
                    "default": "down",
                },
                "amount": {
                    "type": "integer",
                    "description": "Number of pixels to scroll. Default: 500.",
                    "default": 500,
                },
            },
        },
        metadata={"source": "builtin", "category": "browser"},
    )
    async def browser_scroll(direction: str = "down", amount: int = 500, context=None) -> str | list:
        bm = _get_browser_manager(context)
        if not bm:
            return "Error: browser not available"
        if not bm.is_running:
            return "Error: no active browser session. Use browser_navigate first."
        try:
            result = await bm.scroll(direction=direction, amount=amount)
            body = f"Scrolled {result['scrolled']} by {result['amount']}px\n**URL:** {result['url']}"
            dom = _format_dom_section(result.get("elements") or [])
            return _build_browser_result(
                body,
                result.get("screenshot", ""),
                context=context,
                dom_section=dom,
            )
        except Exception as e:
            return f"Error scrolling: {e}"

    @registry.register(
        name="browser_close",
        description="Close the browser and release all resources.",
        parameters={"type": "object", "properties": {}},
        metadata={"source": "builtin", "category": "browser"},
    )
    async def browser_close(context=None) -> str:
        bm = _get_browser_manager(context) if context else None
        if not bm:
            return "No browser session to close."
        try:
            await bm.close()
            if context and "_browser_manager" in context.metadata:
                del context.metadata["_browser_manager"]
            return "Browser closed successfully."
        except Exception as e:
            return f"Error closing browser: {e}"

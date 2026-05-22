from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from typing import Any

from crabagent.core.agent.tools.registry import registry

logger = logging.getLogger(__name__)

PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.async_api import Browser, BrowserContext, Page, async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass


class BrowserManager:
    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._headless = os.environ.get("CRAB_BROWSER_HEADLESS", "true").lower() == "true"

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

    async def navigate(self, url: str, wait_until: str = "domcontentloaded") -> dict[str, Any]:
        await self.ensure_started()
        response = await self._page.goto(url, wait_until=wait_until, timeout=30000)
        title = await self._page.title()
        status = response.status if response else None
        content = await self._extract_text(max_length=3000)
        screenshot_path = await self._take_screenshot()
        return {
            "url": self._page.url,
            "title": title,
            "status": status,
            "content_preview": content,
            "screenshot": screenshot_path,
        }

    async def click(self, selector: str, text: str | None = None) -> dict[str, Any]:
        await self.ensure_started()
        if text and not selector:
            selector = f"text={text}"
        await self._page.click(selector, timeout=10000)
        await self._page.wait_for_load_state("domcontentloaded", timeout=10000)
        title = await self._page.title()
        content = await self._extract_text(max_length=2000)
        return {
            "clicked": selector or text,
            "url": self._page.url,
            "title": title,
            "content_preview": content,
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
        return {
            "typed_in": selector,
            "url": self._page.url,
            "title": title,
            "content_preview": content,
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
        return {"scrolled": direction, "amount": amount, "url": self._page.url}

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
        await self._page.screenshot(path=path, full_page=full_page)
        return path


def _get_browser_manager(context: Any) -> BrowserManager | None:
    if context is None:
        return None
    bm = context.metadata.get("_browser_manager")
    if bm is None:
        bm = BrowserManager()
        context.metadata["_browser_manager"] = bm
    return bm


if PLAYWRIGHT_AVAILABLE:

    @registry.register(
        name="browser_navigate",
        description=(
            "Navigate to a URL in a headless browser. "
            "Returns page title, URL, content preview, and a screenshot file path."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to navigate to.",
                },
                "wait_until": {
                    "type": "string",
                    "description": (
                        "When to consider navigation complete. "
                        "Options: 'domcontentloaded', 'load', 'networkidle'. "
                        "Default: 'domcontentloaded'."
                    ),
                    "default": "domcontentloaded",
                },
            },
            "required": ["url"],
        },
        requires_permission=True,
        metadata={"source": "builtin", "category": "browser"},
    )
    async def browser_navigate(url: str, wait_until: str = "domcontentloaded", context=None) -> str:
        bm = _get_browser_manager(context)
        if not bm:
            return "Error: browser not available"
        try:
            result = await bm.navigate(url, wait_until=wait_until)
            lines = [
                f"**Title:** {result['title']}",
                f"**URL:** {result['url']}",
                f"**Status:** {result['status']}",
                f"**Screenshot:** {result['screenshot']}",
                "",
                result["content_preview"],
            ]
            return "\n".join(lines)
        except Exception as e:
            return f"Error navigating to {url}: {e}"

    @registry.register(
        name="browser_click",
        description="Click an element on the current page. Use CSS selector or visible text to identify the element.",
        parameters={
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector of the element to click (e.g., '#submit-btn', 'a.login').",
                },
                "text": {
                    "type": "string",
                    "description": "Visible text of the element to click (alternative to selector, e.g., 'Sign in').",
                },
            },
        },
        requires_permission=True,
        metadata={"source": "builtin", "category": "browser"},
    )
    async def browser_click(selector: str | None = None, text: str | None = None, context=None) -> str:
        bm = _get_browser_manager(context)
        if not bm:
            return "Error: browser not available"
        if not selector and not text:
            return "Error: provide either 'selector' or 'text'"
        try:
            result = await bm.click(selector=selector or "", text=text)
            lines = [
                f"**Clicked:** {result['clicked']}",
                f"**URL:** {result['url']}",
                f"**Title:** {result['title']}",
                "",
                result["content_preview"],
            ]
            return "\n".join(lines)
        except Exception as e:
            return f"Error clicking element: {e}"

    @registry.register(
        name="browser_type",
        description="Type text into an input field on the current page. Optionally submit the form after typing.",
        parameters={
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector of the input field (e.g., '#search', 'input[name=\"q\"]').",
                },
                "text": {
                    "type": "string",
                    "description": "The text to type into the field.",
                },
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
    async def browser_type(selector: str, text: str, submit: bool = False, context=None) -> str:
        bm = _get_browser_manager(context)
        if not bm:
            return "Error: browser not available"
        try:
            result = await bm.type_text(selector, text, submit=submit)
            lines = [
                f"**Typed into:** {result['typed_in']}",
                f"**URL:** {result['url']}",
                f"**Title:** {result['title']}",
                "",
                result["content_preview"],
            ]
            return "\n".join(lines)
        except Exception as e:
            return f"Error typing text: {e}"

    @registry.register(
        name="browser_screenshot",
        description="Take a screenshot of the current page. Returns the file path of the saved screenshot image.",
        parameters={
            "type": "object",
            "properties": {
                "full_page": {
                    "type": "boolean",
                    "description": "Whether to capture the full scrollable page. Default: false (viewport only).",
                    "default": False,
                },
            },
        },
        metadata={"source": "builtin", "category": "browser"},
    )
    async def browser_screenshot(full_page: bool = False, context=None) -> str:
        bm = _get_browser_manager(context)
        if not bm:
            return "Error: browser not available"
        if not bm.is_running:
            return "Error: no active browser session. Use browser_navigate first."
        try:
            result = await bm.screenshot(full_page=full_page)
            return f"Screenshot saved to: {result['screenshot']}\nURL: {result['url']}\nTitle: {result['title']}"
        except Exception as e:
            return f"Error taking screenshot: {e}"

    @registry.register(
        name="browser_extract",
        description=(
            "Extract text content from the current page. "
            "Optionally target a specific element using a CSS selector."
        ),
        parameters={
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": (
                        "CSS selector to extract content from a specific element. "
                        "If omitted, extracts from the full page body."
                    ),
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
        description="Scroll the current page up or down.",
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
    async def browser_scroll(direction: str = "down", amount: int = 500, context=None) -> str:
        bm = _get_browser_manager(context)
        if not bm:
            return "Error: browser not available"
        if not bm.is_running:
            return "Error: no active browser session. Use browser_navigate first."
        try:
            result = await bm.scroll(direction=direction, amount=amount)
            return f"Scrolled {result['scrolled']} by {result['amount']}px\nURL: {result['url']}"
        except Exception as e:
            return f"Error scrolling: {e}"

    @registry.register(
        name="browser_close",
        description=(
            "Close the browser and release all resources. "
            "Use when done with browser automation to free memory."
        ),
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

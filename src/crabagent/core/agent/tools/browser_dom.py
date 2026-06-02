"""DOM element labelling for the browser tool.

Inspired by browser-use: injects ``data-crab-idx`` attributes onto every
visible interactive element on a page, then returns a compact list of
``{index, tag, role, text, selector}`` for the LLM to reference.

The LLM can then call ``browser_click_index(index=N)`` instead of guessing
CSS selectors. The BrowserManager caches the labelled elements list so
``click_index`` is an O(1) lookup.

The injected JavaScript is deliberately defensive: it skips elements that
are hidden, disabled, or zero-sized, caps the list at ``MAX_LABELS`` to keep
LLM context bounded, and falls back gracefully on any error.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

MAX_LABELS = 80

# JavaScript executed inside the page via page.evaluate(). Returns the list
# of labelled elements. The script is wrapped in an IIFE so it doesn't leak
# globals, and uses ``document.querySelectorAll`` with a broad selector that
# captures anchors, buttons, inputs, selects, textareas, and ARIA-role buttons.
_LABEL_JS_TEMPLATE = r"""
() => {
  const MAX = __MAX_LABELS__;
  const INTERACTIVE = (
    'a, button, input, select, textarea, ' +
    '[role="button"], [role="link"], [role="checkbox"], [role="radio"], ' +
    '[role="tab"], [role="menuitem"], [role="option"], [onclick]'
  );
  const nodes = document.querySelectorAll(INTERACTIVE);
  const results = [];
  let idx = 1;

  function buildSelector(node) {
    const parts = [];
    let cur = node;
    while (cur && cur.nodeType === 1 && cur !== document.body && cur !== document.documentElement) {
      let part = cur.tagName.toLowerCase();
      if (cur.id) {
        part = '#' + CSS.escape(cur.id);
        parts.unshift(part);
        break;
      }
      const parent = cur.parentNode;
      if (parent) {
        const sameTag = Array.from(parent.children).filter(function (c) { return c.tagName === cur.tagName; });
        if (sameTag.length > 1) {
          const pos = sameTag.indexOf(cur) + 1;
          part += ':nth-of-type(' + pos + ')';
        }
      }
      if (cur.getAttribute('role')) part += '[role="' + cur.getAttribute('role') + '"]';
      parts.unshift(part);
      cur = cur.parentNode;
    }
    return parts.join(' > ');
  }

  for (const el of nodes) {
    if (results.length >= MAX) break;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) continue;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    if (style.opacity === '0') continue;
    if (el.disabled === true) continue;
    if (el.getAttribute('aria-hidden') === 'true') continue;
    if (el.tagName === 'INPUT' && el.type === 'hidden') continue;

    let text = '';
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') {
      text = el.placeholder || el.value || el.getAttribute('aria-label') || el.name || '';
    } else {
      text = (el.innerText || el.textContent || '').trim();
      if (!text) text = el.getAttribute('aria-label') || el.title || '';
    }

    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') || '';
    let typeAttr = el.getAttribute('type') || '';
    if (tag === 'input' && !typeAttr) typeAttr = 'text';

    el.setAttribute('data-crab-idx', String(idx));

    results.push({
      idx: idx,
      tag: tag,
      role: role,
      type: typeAttr,
      name: el.name || '',
      placeholder: el.placeholder || '',
      text: String(text).slice(0, 80),
      href: tag === 'a' ? (el.href || '') : '',
      selector: buildSelector(el)
    });
    idx += 1;
  }
  return results;
}
"""

_LABEL_JS = _LABEL_JS_TEMPLATE.replace("__MAX_LABELS__", str(MAX_LABELS))


# JavaScript to remove our labels (called on page navigation)
_UNLABEL_JS = r"""
() => {
  document.querySelectorAll('[data-crab-idx]').forEach((el) => {
    el.removeAttribute('data-crab-idx');
  });
}
"""


async def label_page_elements(page) -> list[dict[str, Any]]:
    """Label visible interactive elements on the current page.

    Returns the list of element descriptors (see ``_LABEL_JS``). The list is
    also cached on the page object via ``page.crab_labeled_elements`` for
    ``browser_click_index`` to consume.
    """

    try:
        elements = await page.evaluate(_LABEL_JS)
    except Exception as exc:
        logger.debug("label_page_elements failed: %s", exc)
        elements = []
    if not isinstance(elements, list):
        elements = []
    # Cache on page for later click_index lookup
    try:
        page.crab_labeled_elements = elements
    except Exception:
        pass
    return elements


async def unlabel_page_elements(page) -> None:
    try:
        await page.evaluate(_UNLABEL_JS)
    except Exception:
        pass


def get_label_cache(page) -> list[dict[str, Any]]:
    elements = getattr(page, "crab_labeled_elements", None)
    if not isinstance(elements, list):
        return []
    return elements


def find_element_by_index(page, index: int) -> dict[str, Any] | None:
    """Look up a labelled element by its 1-based index. Returns ``None`` if
    the index is out of range or the cache is empty."""
    if index < 1:
        return None
    elements = get_label_cache(page)
    if not elements:
        return None
    for el in elements:
        if el.get("idx") == index:
            return el
    return None


def format_elements_for_llm(elements: list[dict[str, Any]], max_to_show: int = 40) -> str:
    """Render the element list as a markdown bullet list for the LLM.

    Each line: ``[N] <tag> "<text>" [<extra hints>]``
    """
    if not elements:
        return "(no interactive elements found)"
    lines: list[str] = []
    for el in elements[:max_to_show]:
        idx = el.get("idx", 0)
        tag = el.get("tag", "?")
        role = el.get("role", "")
        text = el.get("text", "")
        type_ = el.get("type", "")
        placeholder = el.get("placeholder", "")
        href = el.get("href", "")

        parts = [f"[{idx}] {tag}"]
        if type_:
            parts.append(f"[{type_}]")
        if role:
            parts.append(f"(role={role})")
        if text:
            safe_text = text.replace("\n", " ").strip()
            if safe_text:
                parts.append(f'"{safe_text}"')
        if placeholder:
            parts.append(f'(placeholder="{placeholder}")')
        if href:
            short = href if len(href) <= 60 else href[:57] + "..."
            parts.append(f"→ {short}")
        lines.append(" ".join(parts))
    if len(elements) > max_to_show:
        lines.append(f"... ({len(elements) - max_to_show} more)")
    return "\n".join(lines)


__all__ = [
    "MAX_LABELS",
    "label_page_elements",
    "unlabel_page_elements",
    "get_label_cache",
    "find_element_by_index",
    "format_elements_for_llm",
]

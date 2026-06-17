import { useRef, useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, AlertTriangle, FileText } from "lucide-react";
import { cn } from "../lib/cn";

interface Props {
  html: string | null;
  loading?: boolean;
  error?: string;
  className?: string;
  onQuickEdit?: (oldText: string, newText: string) => void;
  /** 用户拖拽列边框调整宽度后触发 */
  onStyleEdit?: (element: string, props: Record<string, string | number | boolean>) => void;
  /** 大纲变化时通知父组件 */
  onOutlineChange?: (items: { level: number; text: string; index: number }[]) => void;
  /** 当前可见的大纲索引变化 */
  onOutlineActive?: (index: number) => void;
  /** 当前编辑元素信息（双击进入编辑时） */
  onEditElement?: (info: { tagName: string; path: string; style: Record<string, string> }) => void;
}

// Injected script for column-resize and row-resize.
// Handles visual drag in-iframe; coordinates with parent for mouseup-outside-iframe.
const RESIZE_SCRIPT = `
<script>
(function() {
  // Column resize state
  var dragCol = null, dragStartX = 0, dragStartPt = 0, dragTh = null;
  // Row resize state
  var dragRow = null, dragStartY = 0, dragStartH = 0, dragRowTh = null;

  function getTable() { return document.querySelector('table'); }

  // ---- Column helpers ----
  function findBorderCol(cx) {
    var hd = document.querySelectorAll('th.col-header');
    for (var i = 0; i < hd.length; i++) {
      var r = hd[i].getBoundingClientRect();
      if (Math.abs(cx - r.right) <= 6) return { th: hd[i], idx: i };
    }
    return null;
  }
  function getColEl(idx) {
    var t = getTable(); if (!t) return null;
    var cols = t.querySelectorAll('colgroup col');
    return cols[idx + 1] || null;
  }
  function parseW(el) {
    if (!el) return 80;
    var m = el.getAttribute('style') && el.getAttribute('style').match(/width:\s*([\d.]+)\s*pt/i);
    return m ? parseFloat(m[1]) : 80;
  }

  // ---- Row helpers ----
  function findBorderRow(cy) {
    var hd = document.querySelectorAll('th.row-header');
    for (var i = 0; i < hd.length; i++) {
      var r = hd[i].getBoundingClientRect();
      if (Math.abs(cy - r.bottom) <= 6) return { th: hd[i], idx: i };
    }
    return null;
  }
  function getRowTr(th) { return th ? th.closest('tr') : null; }
  function parseH(el) {
    if (!el) return 20;
    var m = el.getAttribute('style') && el.getAttribute('style').match(/height:\s*([\d.]+)\s*pt/i);
    if (m) return parseFloat(m[1]);
    var r = el.getBoundingClientRect();
    return Math.round((r.height * 0.75) * 100) / 100;
  }

  // ---- Finish column resize ----
  function finishCol() {
    if (!dragCol || !dragTh) return;
    var p = parseW(dragCol);
    var w = Math.max(1, Math.round((p / 5.251) * 100) / 100);
    var path = dragTh.getAttribute('data-path');
    dragCol = null; dragTh = null;
    document.body.style.cursor = ''; document.body.style.userSelect = '';
    window.parent.postMessage({ type: 'col-resize-active', active: false }, '*');
    if (path && w > 0) window.parent.postMessage({ type: 'col-resize', element: path, props: { width: w } }, '*');
  }

  // ---- Finish row resize ----
  function finishRow() {
    if (!dragRow || !dragRowTh) return;
    var tr = getRowTr(dragRowTh);
    var p = tr ? parseH(tr) : dragStartH;
    var h = Math.max(5, Math.round(p * 100) / 100);
    var path = dragRowTh.getAttribute('data-path');
    dragRow = null; dragRowTh = null;
    document.body.style.cursor = ''; document.body.style.userSelect = '';
    window.parent.postMessage({ type: 'row-resize-active', active: false }, '*');
    if (path && h > 0) window.parent.postMessage({ type: 'row-resize', element: path, props: { height: h } }, '*');
  }

  // ---- Hover cursors ----
  document.addEventListener('mousemove', function(e) {
    if (dragCol || dragRow) return;
    var t = e.target;
    if (t && t.closest('thead')) {
      var bc = findBorderCol(e.clientX);
      document.body.style.cursor = bc ? 'col-resize' : '';
    } else if (t && t.closest('tbody')) {
      var br = findBorderRow(e.clientY);
      document.body.style.cursor = br ? 'row-resize' : '';
    } else {
      document.body.style.cursor = '';
    }
  });

  // ---- Start drag ----
  document.addEventListener('mousedown', function(e) {
    if (e.button !== 0) return;
    var t = e.target;
    if (t && t.closest('thead')) {
      var bc = findBorderCol(e.clientX);
      if (!bc) return;
      e.preventDefault();
      var el = getColEl(bc.idx); if (!el) return;
      dragTh = bc.th; dragCol = el;
      dragStartX = e.clientX; dragStartPt = parseW(el);
      document.body.style.cursor = 'col-resize'; document.body.style.userSelect = 'none';
      window.parent.postMessage({ type: 'col-resize-active', active: true }, '*');
    } else if (t && t.closest('tbody')) {
      var br = findBorderRow(e.clientY);
      if (!br) return;
      e.preventDefault();
      var tr = getRowTr(br.th); if (!tr) return;
      dragRowTh = br.th; dragRow = tr;
      dragStartY = e.clientY; dragStartH = parseH(tr);
      document.body.style.cursor = 'row-resize'; document.body.style.userSelect = 'none';
      window.parent.postMessage({ type: 'row-resize-active', active: true }, '*');
    }
  });

  // ---- Drag update ----
  document.addEventListener('mousemove', function(e) {
    if (dragCol) {
      var newColPt = Math.max(10, dragStartPt + (e.clientX - dragStartX) * 0.75);
      dragCol.style.width = newColPt + 'pt';
      var tbl = getTable();
      if (tbl) {
        var total = 0;
        var cs = tbl.querySelectorAll('colgroup col');
        for (var ci = 0; ci < cs.length; ci++) {
          var sw = cs[ci].getAttribute('style') && cs[ci].getAttribute('style').match(/width:\s*([\d.]+)\s*pt/i);
          total += sw ? parseFloat(sw[1]) : 0;
        }
        tbl.style.width = Math.max(total, 50) + 'pt';
      }
    } else if (dragRow) {
      dragRow.style.height = Math.max(5, dragStartH + (e.clientY - dragStartY) * 0.75) + 'pt';
    }
  });

  // ---- Mouseup inside iframe ----
  document.addEventListener('mouseup', function(e) {
    if (dragCol) finishCol(); else if (dragRow) finishRow();
  });

  // ---- Mouseup outside iframe ----
  window.addEventListener('message', function(e) {
    if (e.data && e.data.type === 'col-resize-finish' && dragCol) finishCol();
    if (e.data && e.data.type === 'row-resize-finish' && dragRow) finishRow();
  });
})();
</script>
`;

// Injected script for inline editing.// Injected script for inline editing.
// Double-click to edit. Escape to cancel. Save triggers:
//   - Click outside element (inside iframe) → mousedown handler
//   - Click outside iframe → parent sends "quick-edit-finish" message
const EDIT_SCRIPT = `
<script>
(function() {
  var el = null, oldText = '';

  document.addEventListener('dblclick', function(e) {
    var t = e.target;
    if (!t || t.tagName === 'BODY' || t.tagName === 'HTML' || t.tagName === 'SCRIPT' || t.tagName === 'STYLE') return;
    // Walk up to find a block-level container (skip inline elements like SPAN)
    var blockTags = ['DIV','P','LI','H1','H2','H3','H4','H5','H6','TD','TH','BLOCKQUOTE','PRE'];
    while (t && t.parentNode && t.parentNode !== document.body) {
      if (blockTags.indexOf(t.tagName) >= 0 && t.textContent.trim()) break;
      t = t.parentNode;
    }
    // If we ended up at body or an empty element, try using the original target
    if (t === document.body || !t.textContent.trim()) {
      t = e.target;
      while (t && t.parentNode && !t.textContent.trim() && blockTags.indexOf(t.tagName) < 0) {
        t = t.parentNode;
      }
    }
    if (!t || t === document.body) return;
    var txt = (t.innerText || t.textContent).trim();
    if (!txt) return;
    t.contentEditable = 'true';
    t.focus();
    try {
      var r = document.createRange();
      r.selectNodeContents(t);
      var s = window.getSelection();
      s.removeAllRanges();
      s.addRange(r);
    } catch(_) {}
    el = t;
    oldText = txt;
    // Notify parent that editing started
    window.parent.postMessage({ type: 'quick-edit-active', active: true }, '*');
  });

  // Escape to cancel
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && el) {
      e.preventDefault();
      cancel();
    }
    // Enter = newline (default)
  });

  // Click inside iframe but outside editing element → save
  document.addEventListener('mousedown', function(e) {
    if (!el) return;
    if (el === e.target || el.contains(e.target)) return; // click inside editing area
    finish();
  }, true);

  // Listen for parent telling us to finish (user clicked outside iframe)
  window.addEventListener('message', function(e) {
    if (e.data?.type === 'quick-edit-finish' && el) {
      finish();
    }
  });

  function finish() {
    if (!el) return;
    var n = (el.innerText || el.textContent).trim();
    el.contentEditable = 'false';
    if (n && n !== oldText) {
      window.parent.postMessage({ type: 'quick-edit', old_text: oldText, new_text: n }, '*');
    }
    el = null;
    oldText = '';
    window.parent.postMessage({ type: 'quick-edit-active', active: false }, '*');
  }

  function cancel() {
    if (!el) return;
    el.innerText = oldText;
    el.contentEditable = 'false';
    el = null;
    oldText = '';
    window.parent.postMessage({ type: 'quick-edit-active', active: false }, '*');
  }
})();
</script>
`;

export function DocumentPreview({ html, loading, error, className, onQuickEdit, onStyleEdit, onOutlineChange, onOutlineActive, onEditElement }: Props) {
  const { t } = useTranslation();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const editHandlerRef = useRef(onQuickEdit);
  const styleHandlerRef = useRef(onStyleEdit);
  const outlineHandlerRef = useRef(onOutlineChange);
  const outlineActiveHandlerRef = useRef(onOutlineActive);
  const editElementHandlerRef = useRef(onEditElement);
  const [editing, setEditing] = useState(false);
  const [resizing, setResizing] = useState(false);
  const resizeActive = useRef(false);
  editHandlerRef.current = onQuickEdit;
  styleHandlerRef.current = onStyleEdit;
  outlineHandlerRef.current = onOutlineChange;
  outlineActiveHandlerRef.current = onOutlineActive;
  editElementHandlerRef.current = onEditElement;

  // Listen for messages from iframe
  useEffect(() => {
    const handler = (e: MessageEvent) => {
      const data = e.data;
      if (!data) return;
      if (data.type === "quick-edit" && data.old_text && data.new_text) {
        editHandlerRef.current?.(data.old_text, data.new_text);
      } else if (data.type === "quick-edit-active") {
        setEditing(!!data.active);
      } else if (data.type === "col-resize" && data.element && data.props) {
        setResizing(true);
        styleHandlerRef.current?.(data.element, data.props);
        setTimeout(() => setResizing(false), 800);
      } else if (data.type === "row-resize" && data.element && data.props) {
        setResizing(true);
        styleHandlerRef.current?.(data.element, data.props);
        setTimeout(() => setResizing(false), 800);
      } else if (data.type === "col-resize-active" || data.type === "row-resize-active") {
        resizeActive.current = !!data.active;
        if (data.active) {
          document.body.style.cursor = data.type === "row-resize-active" ? 'row-resize' : 'col-resize';
          document.body.style.userSelect = 'none';
        } else {
          document.body.style.cursor = '';
          document.body.style.userSelect = '';
        }
      } else if (data.type === "doc-outline" && data.items) {
        outlineHandlerRef.current?.(data.items as { level: number; text: string; index: number }[]);
      } else if (data.type === "doc-outline-active") {
        outlineActiveHandlerRef.current?.(data.index as number);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  // Forward mouseup outside iframe → col/row-resize-finish to iframe
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (!resizeActive.current) return;
      const iframe = iframeRef.current;
      if (!iframe) return;
      const rect = iframe.getBoundingClientRect();
      if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) {
        iframe.contentWindow?.postMessage({ type: 'col-resize-finish' }, '*');
        iframe.contentWindow?.postMessage({ type: 'row-resize-finish' }, '*');
      }
    };
    window.addEventListener("mouseup", handler);
    return () => window.removeEventListener("mouseup", handler);
  }, []);

  // When editing is active, listen for clicks on the parent page
  // to send "finish" to the iframe.
  useEffect(() => {
    if (!editing) return;
    const handler = (e: MouseEvent) => {
      const iframe = iframeRef.current;
      if (!iframe) return;
      // Check if click is outside the iframe
      const rect = iframe.getBoundingClientRect();
      const x = e.clientX, y = e.clientY;
      if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) {
        iframe.contentWindow?.postMessage({ type: "quick-edit-finish" }, "*");
      }
    };
    // Use capture phase to catch clicks before they reach iframe
    window.addEventListener("mousedown", handler, true);
    return () => window.removeEventListener("mousedown", handler, true);
  }, [editing]);

  if (loading) {
    return (
      <div className={cn("flex flex-col items-center justify-center h-full gap-3", className)}>
        <Loader2 size={24} className="animate-spin text-[var(--text-tertiary)]" />
        <span className="text-xs text-[var(--text-tertiary)]">{t("document.loadingPreview")}</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className={cn("flex flex-col items-center justify-center h-full gap-3 p-6", className)}>
        <AlertTriangle size={24} className="text-[var(--danger)]" />
        <span className="text-xs text-[var(--danger)] text-center">{error}</span>
      </div>
    );
  }

  if (!html) {
    return (
      <div className={cn("flex flex-col items-center justify-center h-full gap-3", className)}>
        <FileText size={28} className="text-[var(--text-tertiary)]" opacity={0.4} />
        <span className="text-xs text-[var(--text-tertiary)]">{t("document.previewFailed")}</span>
      </div>
    );
  }

  // Injected script for outline extraction + scroll tracking + highlight + element info.
const OUTLINE_SCRIPT = `
<script>
(function() {
  function extractOutline() {
    var headings = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
    var items = [];
    headings.forEach(function(h, i) {
      h.setAttribute('data-outline-idx', i);
      items.push({
        level: parseInt(h.tagName[1]),
        text: h.textContent.trim().substring(0, 80),
        index: i
      });
    });
    window.parent.postMessage({ type: 'doc-outline', items: items }, '*');
  }

  setTimeout(extractOutline, 200);

  var outlineTimer = null;
  var observer = new MutationObserver(function() {
    if (outlineTimer) clearTimeout(outlineTimer);
    outlineTimer = setTimeout(extractOutline, 300);
  });
  observer.observe(document.body, { childList: true, subtree: true });

  // Scroll tracking — update active heading
  var scrollTimer = null;
  window.addEventListener('scroll', function() {
    if (scrollTimer) return;
    scrollTimer = setTimeout(function() {
      scrollTimer = null;
      var headings = document.querySelectorAll('[data-outline-idx]');
      var activeIdx = 0;
      headings.forEach(function(h) {
        var rect = h.getBoundingClientRect();
        if (rect.top < 80) {
          activeIdx = parseInt(h.getAttribute('data-outline-idx'));
        }
      });
      window.parent.postMessage({ type: 'doc-outline-active', index: activeIdx }, '*');
    }, 100);
  });

  // Listen for scroll requests from parent
  window.addEventListener('message', function(e) {
    if (e.data && e.data.type === 'doc-outline-scroll') {
      var el = document.querySelector('[data-outline-idx="' + e.data.index + '"]');
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });

  // Listen for highlight requests from parent
  window.addEventListener('message', function(e) {
    if (e.data && e.data.type === 'highlight-element') {
      var target = null;
      // Try data-path first
      if (e.data.path) {
        target = document.querySelector('[data-path="' + e.data.path + '"]');
      }
      // Fallback: try text matching
      if (!target && e.data.text) {
        var candidates = document.querySelectorAll('p, td, h1, h2, h3, h4, span, div');
        for (var i = 0; i < candidates.length; i++) {
          if (candidates[i].textContent.includes(e.data.text)) {
            target = candidates[i];
            break;
          }
        }
      }
      if (!target) return;
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      var orig = target.style.backgroundColor;
      var origTransition = target.style.transition;
      target.style.transition = 'background-color 0.3s';
      target.style.backgroundColor = 'rgba(255, 230, 0, 0.35)';
      setTimeout(function() {
        target.style.backgroundColor = orig;
        setTimeout(function() { target.style.transition = origTransition; }, 500);
      }, 2500);
    }
  });
})();
</script>
`;

const allScripts = `${RESIZE_SCRIPT}\n${EDIT_SCRIPT}\n${OUTLINE_SCRIPT}`;
  const injectedHtml = html.includes("</body>")
    ? html.replace("</body>", `${allScripts}\n</body>`)
    : html + allScripts;

  return (
    <div className={cn("relative h-full", className)}>
      {editing && (
        <div className="absolute top-2 right-2 z-40 px-2 py-1 rounded-lg text-[10px] bg-blue-500 text-white shadow-md">
          Editing... (click outside to save)
        </div>
      )}
      {resizing && (
        <div className="absolute top-2 left-2 z-40 px-2 py-1 rounded-lg text-[10px] bg-green-600 text-white shadow-md">
          Resizing...
        </div>
      )}
      <iframe
        ref={iframeRef}
        srcDoc={injectedHtml}
        title="Document Preview"
        className="w-full h-full border-0"
        sandbox="allow-scripts allow-same-origin"
        style={{ background: "#fff" }}
      />
    </div>
  );
}

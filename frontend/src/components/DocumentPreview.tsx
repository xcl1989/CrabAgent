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
}

// Injected script for inline editing.
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

export function DocumentPreview({ html, loading, error, className, onQuickEdit }: Props) {
  const { t } = useTranslation();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const editHandlerRef = useRef(onQuickEdit);
  const [editing, setEditing] = useState(false);
  editHandlerRef.current = onQuickEdit;

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      const data = e.data;
      if (!data) return;
      if (data.type === "quick-edit" && data.old_text && data.new_text) {
        editHandlerRef.current?.(data.old_text, data.new_text);
      } else if (data.type === "quick-edit-active") {
        setEditing(!!data.active);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
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

  const injectedHtml = html.includes("</body>")
    ? html.replace("</body>", `${EDIT_SCRIPT}\n</body>`)
    : html + EDIT_SCRIPT;

  return (
    <div className={cn("relative h-full", className)}>
      {editing && (
        <div className="absolute top-2 right-2 z-40 px-2 py-1 rounded-lg text-[10px] bg-blue-500 text-white shadow-md">
          Editing... (click outside to save)
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

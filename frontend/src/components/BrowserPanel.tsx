import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Globe2, Loader2, RefreshCw, ShieldCheck, Square } from "lucide-react";

interface BrowserState {
  url: string;
  title: string;
  canGoBack: boolean;
  canGoForward: boolean;
  loading: boolean;
}

const START_URL = "https://www.google.com/";

function formatUrl(url: string): string {
  if (!url) return START_URL;
  return /^[a-z][a-z\d+.-]*:/i.test(url) ? url : `https://${url}`;
}

type BrowserAction = "back" | "forward" | "reload" | "stop";

export default function BrowserPanel() {
  const hostRef = useRef<HTMLDivElement>(null);
  const addressEditingRef = useRef(false);
  const pendingNavigationRef = useRef<string | null>(null);
  const lastBoundsRef = useRef("");
  const syncTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [available, setAvailable] = useState(Boolean(window.electronAPI?.collaborationBrowserLayout));
  const [browserState, setBrowserState] = useState<BrowserState>({
    url: START_URL,
    title: "协作浏览器",
    canGoBack: false,
    canGoForward: false,
    loading: false,
  });
  const [address, setAddress] = useState(START_URL);
  const [error, setError] = useState("");

  const syncBounds = useCallback(() => {
    if (syncTimerRef.current) clearTimeout(syncTimerRef.current);
    syncTimerRef.current = setTimeout(() => {
      const host = hostRef.current;
      const bridge = window.electronAPI?.collaborationBrowserLayout;
      if (!host || !bridge) return;
      const rect = host.getBoundingClientRect();
      const w = Math.round(rect.width);
      const h = Math.round(rect.height);
      if (w < 10 || h < 10) return;
      const key = `${Math.round(rect.left)},${Math.round(rect.top)},${w},${h}`;
      if (key === lastBoundsRef.current) return;
      lastBoundsRef.current = key;
      void bridge({ x: rect.left, y: rect.top, width: rect.width, height: rect.height }, true).catch(() => {});
    }, 200);
  }, []);

  useEffect(() => {
    const bridge = window.electronAPI?.collaborationBrowserLayout;
    setAvailable(Boolean(bridge));
    if (!bridge) return;
    const observer = new ResizeObserver(syncBounds);
    if (hostRef.current) observer.observe(hostRef.current);
    syncBounds();
    return () => {
      observer.disconnect();
      void bridge(null, false).catch(() => {});
    };
  }, [syncBounds]);

  useEffect(() => {
    window.electronAPI?.onCollaborationBrowserState?.((next) => {
      setBrowserState(next);
      const pending = pendingNavigationRef.current;
      if (!addressEditingRef.current && (!pending || next.url === pending)) {
        setAddress(next.url || "");
        if (pending && next.url === pending) pendingNavigationRef.current = null;
      }
      setError("");
    });
  }, []);

  const navigate = useCallback(async () => {
    const bridge = window.electronAPI?.collaborationBrowserNavigate;
    if (!bridge) return;
    const target = formatUrl(address);
    pendingNavigationRef.current = target;
    addressEditingRef.current = false;
    setAddress(target);
    try {
      setError("");
      await bridge(target);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [address]);

  const action = useCallback((name: BrowserAction) => {
    void window.electronAPI?.collaborationBrowserAction?.(name).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : "浏览器操作失败");
    });
  }, []);

  if (!available) {
    return (
      <div className="flex h-full items-center justify-center bg-[var(--bg-primary)] p-6">
        <div className="max-w-sm rounded-2xl border border-[var(--border)] bg-[var(--bg-secondary)] p-6 text-center">
          <Globe2 size={28} className="mx-auto mb-3 text-[var(--brand)]" />
          <p className="text-sm font-medium text-[var(--text-primary)]">协作浏览器仅在桌面版可用</p>
          <p className="mt-2 text-xs text-[var(--text-tertiary)]">请从 Electron 桌面应用使用此功能。</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-[var(--bg-primary)]">
      {/* Address bar */}
      <div className="shrink-0 border-b border-[var(--border)] bg-[var(--bg-secondary)] px-2 py-1.5">
        <form className="flex items-center gap-1.5" onSubmit={(e) => { e.preventDefault(); void navigate(); }}>
          <button type="button" onClick={() => action("back")} disabled={!browserState.canGoBack} className="browser-control" title="后退"><ArrowLeft size={15} /></button>
          <button type="button" onClick={() => action("forward")} disabled={!browserState.canGoForward} className="browser-control" title="前进"><ArrowRight size={15} /></button>
          <button type="button" onClick={() => action(browserState.loading ? "stop" : "reload")} className="browser-control" title={browserState.loading ? "停止" : "刷新"}>
            {browserState.loading ? <Square size={13} /> : <RefreshCw size={14} />}
          </button>
          <div className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-2.5 focus-within:border-[var(--brand-border)]">
            <ShieldCheck size={14} className="shrink-0 text-[var(--brand)]" />
            <input
              value={address}
              onFocus={() => { addressEditingRef.current = true; }}
              onBlur={() => { addressEditingRef.current = false; }}
              onChange={(e) => setAddress(e.target.value)}
              onKeyDownCapture={(e) => {
                if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); void navigate(); }
              }}
              className="min-w-0 flex-1 bg-transparent py-1.5 text-sm text-[var(--text-primary)] outline-none"
              aria-label="网站地址"
            />
            {browserState.loading ? <Loader2 size={13} className="shrink-0 animate-spin text-[var(--text-tertiary)]" /> : <ShieldCheck size={13} className="shrink-0 text-[var(--success)]" />}
          </div>
          <button type="submit" className="rounded-lg bg-[var(--brand)] px-3 py-1.5 text-xs font-medium text-[var(--text-on-brand)] transition-colors hover:bg-[var(--brand-hover)]">打开</button>
        </form>
        {error && <p className="mt-1 px-1 text-xs text-[var(--danger)]">{error}</p>}
      </div>

      {/* Native web view host */}
      <div className="relative min-h-0 flex-1 bg-white">
        <div ref={hostRef} className="absolute inset-0" />
      </div>

      <style>{`.browser-control { display: inline-flex; height: 30px; width: 30px; align-items: center; justify-content: center; border-radius: 8px; color: var(--text-secondary); transition: background-color 150ms, color 150ms; } .browser-control:hover:not(:disabled) { background: var(--bg-tertiary); color: var(--text-primary); } .browser-control:disabled { cursor: not-allowed; opacity: .35; }`}</style>
    </div>
  );
}

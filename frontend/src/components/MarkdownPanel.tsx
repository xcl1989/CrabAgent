import { useState, useEffect, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Save, FileText, Code2, Eye, Columns2, AlertTriangle } from "lucide-react";
import { cn } from "../lib/cn";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { readFile, saveFile } from "../api/files";

type ViewMode = "split" | "source" | "preview";

interface Props {
  filePath: string;
  className?: string;
  onClose?: () => void;
}

export function MarkdownPanel({ filePath, className, onClose }: Props) {
  const { t } = useTranslation();
  const [source, setSource] = useState("");
  const [originalSource, setOriginalSource] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("split");
  const [loading, setLoading] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const fileName = filePath.split("/").pop() || filePath;

  // ── Load file content ──────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    readFile(filePath)
      .then((res) => {
        if (cancelled) return;
        setSource(res.content);
        setOriginalSource(res.content);
        setDirty(false);
      })
      .catch((e: any) => {
        if (!cancelled) setError(e?.message || "Failed to load file");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [filePath]);

  // ── Save ───────────────────────────────────────────────────
  const handleSave = useCallback(async () => {
    if (!dirty) return;
    setSaving(true);
    try {
      await saveFile(filePath, source);
      setOriginalSource(source);
      setDirty(false);
      setError(null);
    } catch (e: any) {
      setError(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  }, [dirty, filePath, source]);

  // ── Keyboard shortcuts (Cmd/Ctrl+S) ────────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        handleSave();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handleSave]);

  const handleEdit = useCallback((val: string) => {
    setSource(val);
    setDirty(val !== originalSource);
  }, [originalSource]);

  // ── Bidirectional scroll sync (editor ↔ preview) ───────────
  const previewRef = useRef<HTMLDivElement>(null);
  const syncingScroll = useRef(false);

  const handleEditorScroll = useCallback(() => {
    if (viewMode !== "split" || syncingScroll.current) return;
    const ta = textareaRef.current;
    const pv = previewRef.current;
    if (!ta || !pv) return;
    const maxScroll = ta.scrollHeight - ta.clientHeight;
    if (maxScroll <= 0) return;
    const ratio = ta.scrollTop / maxScroll;
    syncingScroll.current = true;
    pv.scrollTop = ratio * (pv.scrollHeight - pv.clientHeight);
    requestAnimationFrame(() => { syncingScroll.current = false; });
  }, [viewMode]);

  const handlePreviewScroll = useCallback(() => {
    if (viewMode !== "split" || syncingScroll.current) return;
    const ta = textareaRef.current;
    const pv = previewRef.current;
    if (!ta || !pv) return;
    const maxScroll = pv.scrollHeight - pv.clientHeight;
    if (maxScroll <= 0) return;
    const ratio = pv.scrollTop / maxScroll;
    syncingScroll.current = true;
    ta.scrollTop = ratio * (ta.scrollHeight - ta.clientHeight);
    requestAnimationFrame(() => { syncingScroll.current = false; });
  }, [viewMode]);

  const lineCount = source.split("\n").length;

  const VIEW_BUTTONS: { mode: ViewMode; icon: typeof Code2; label: string }[] = [
    { mode: "source", icon: Code2, label: t("markdownPanel.source") },
    { mode: "split", icon: Columns2, label: t("markdownPanel.split") },
    { mode: "preview", icon: Eye, label: t("markdownPanel.preview") },
  ];

  if (loading) {
    return (
      <div className={cn("flex items-center justify-center h-full text-[var(--text-tertiary)]", className)}>
        <div className="w-6 h-6 border-2 border-[var(--border)] border-t-[var(--brand)] rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col h-full bg-[var(--bg-primary)]", className)}>
      {/* ── Toolbar ─────────────────────────────────────────── */}
      <div className="flex items-center gap-1 px-3 h-11 border-b border-[var(--border)] bg-[var(--bg-secondary)] shrink-0">
        {/* View mode switcher */}
        <div className="flex items-center gap-0.5 rounded-md bg-[var(--bg-tertiary)] p-0.5">
          {VIEW_BUTTONS.map(({ mode, icon: Icon, label }) => (
            <button
              key={mode}
              onClick={() => setViewMode(mode)}
              className={cn(
                "flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] font-medium transition-colors",
                viewMode === mode
                  ? "bg-[var(--bg-primary)] text-[var(--brand)] shadow-sm"
                  : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]",
              )}
            >
              <Icon size={12} />
              {label}
            </button>
          ))}
        </div>

        <div className="flex-1" />

        {/* File name */}
        <span className="text-sm font-medium truncate text-[var(--text-primary)] max-w-[200px]" title={fileName}>
          {fileName}
        </span>

        {/* Save button */}
        {dirty && (
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1 px-2 py-1 ml-2 rounded text-[11px] text-[var(--accent)] hover:bg-[var(--accent-bg)] transition-colors disabled:opacity-50"
          >
            <Save size={11} />
            {saving ? "Saving..." : t("common.save")}
          </button>
        )}

        {onClose && (
          <button
            onClick={onClose}
            className="ml-1 p-1 rounded text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
          >
            <span className="text-xs">✕</span>
          </button>
        )}
      </div>

      {/* ── Main content ────────────────────────────────────── */}
      <div className="flex-1 flex min-h-0">
        {/* Left: Source editor (visible in source & split) */}
        {(viewMode === "source" || viewMode === "split") && (
          <div className={cn(
            "flex min-h-0",
            viewMode === "split" ? "w-1/2 border-r border-[var(--border)]" : "w-full",
          )}>
            {/* Line numbers */}
            <div className="select-none text-right px-2 py-3 text-[12px] leading-[1.6] font-mono text-[var(--text-tertiary)] bg-[var(--bg-secondary)] border-r border-[var(--border)] shrink-0 overflow-hidden">
              {Array.from({ length: lineCount }, (_, i) => (
                <div key={i}>{i + 1}</div>
              ))}
            </div>

            {/* Textarea */}
            <textarea
              ref={textareaRef}
              value={source}
              onChange={(e) => handleEdit(e.target.value)}
              onScroll={handleEditorScroll}
              className="flex-1 bg-transparent text-[var(--text-primary)] text-[12px] leading-[1.6] font-mono p-3 border-0 resize-none outline-none"
              style={{ tabSize: 4, whiteSpace: "pre", overflowWrap: "normal", overflowX: "auto" }}
              spellCheck={false}
            />
          </div>
        )}

        {/* Right: Rendered preview (visible in preview & split) */}
        {(viewMode === "preview" || viewMode === "split") && (
          <div
            ref={previewRef}
            onScroll={handlePreviewScroll}
            className={cn(
              "overflow-auto p-6 bg-[var(--bg-primary)]",
              viewMode === "split" ? "w-1/2" : "w-full",
            )}
          >
            <div className="markdown-body max-w-[800px] mx-auto">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeHighlight]}
              >
                {source || `*${t("markdownPanel.empty")}*`}
              </ReactMarkdown>
            </div>
          </div>
        )}
      </div>

      {/* ── Status bar ──────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3 py-1 border-t border-[var(--border)] bg-[var(--bg-secondary)] shrink-0">
        <div className="flex items-center gap-2">
          <FileText size={10} className="text-[var(--text-tertiary)]" />
          <span className="text-[10px] font-mono text-[var(--text-tertiary)]">markdown</span>
          {dirty && (
            <span className="text-[10px] text-[var(--warning)]">● {t("markdownPanel.modified")}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {error && (
            <span className="text-[10px] text-[var(--danger)] flex items-center gap-1">
              <AlertTriangle size={10} /> {error}
            </span>
          )}
          <span className="text-[10px] font-mono text-[var(--text-tertiary)]">
            {lineCount} lines
          </span>
        </div>
      </div>
    </div>
  );
}

import { useState, useCallback, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Save, Code, AlertTriangle } from "lucide-react";
import { cn } from "../lib/cn";
import { CodeTabs } from "./CodeTabs";
import * as filesApi from "../api/files";

interface CodeTabState {
  path: string;
  name: string;
  content: string;
  originalContent: string;
  modified: boolean;
  language: string;
}

interface Props {
  initialPath?: string;
  initialContent?: string;
  className?: string;
  workMode?: boolean;
}

function detectLanguage(name: string): string {
  const ext = name.split(".").pop()?.toLowerCase() || "";
  const langMap: Record<string, string> = {
    py: "python", ts: "typescript", tsx: "typescriptreact",
    js: "javascript", jsx: "javascriptreact", json: "json",
    go: "go", rs: "rust", java: "java", c: "c", cpp: "cpp",
    css: "css", scss: "scss", html: "html", vue: "vue",
    svelte: "svelte", md: "markdown", yaml: "yaml", yml: "yaml",
    toml: "toml", sql: "sql", sh: "bash", bash: "bash",
    dockerfile: "dockerfile", txt: "text",
  };
  return langMap[ext] || "text";
}

export function CodePanel({ initialPath, initialContent, className, workMode }: Props) {
  const { t } = useTranslation();
  const [tabs, setTabs] = useState<CodeTabState[]>(() => initialPath && initialContent !== undefined
    ? [{ path: initialPath, name: initialPath.split("/").pop() || initialPath, content: initialContent, originalContent: initialContent, modified: false, language: detectLanguage(initialPath) }]
    : [],
  );
  const [activePath, setActivePath] = useState<string | null>(initialPath || null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const activeTab = tabs.find((t) => t.path === activePath);

  const openFile = useCallback(async (path: string) => {
    try {
      const result = await filesApi.readFile(path);
      const name = path.split("/").pop() || path;
      setTabs((prev) => {
        if (prev.some((t) => t.path === path)) return prev;
        return [...prev, { path, name, content: result.content, originalContent: result.content, modified: false, language: detectLanguage(path) }];
      });
      setActivePath(path);
      setError(null);
    } catch (e: any) {
      setError(e?.message || "Failed to open file");
    }
  }, []);

  const closeTab = useCallback((path: string) => {
    setTabs((prev) => {
      const idx = prev.findIndex((t) => t.path === path);
      const next = prev.filter((t) => t.path !== path);
      if (activePath === path) {
        const newIdx = Math.min(idx, next.length - 1);
        setActivePath(next[newIdx]?.path || null);
      }
      return next;
    });
  }, [activePath]);

  const handleEdit = useCallback((content: string) => {
    setTabs((prev) => prev.map((t) => t.path === activePath ? { ...t, content, modified: content !== t.originalContent } : t));
  }, [activePath]);

  const handleSave = useCallback(async () => {
    if (!activeTab || !activeTab.modified) return;
    setSaving(true);
    try {
      await filesApi.saveFile(activeTab.path, activeTab.content);
      setTabs((prev) => prev.map((t) => t.path === activePath ? { ...t, originalContent: t.content, modified: false } : t));
      setError(null);
    } catch (e: any) {
      setError(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  }, [activeTab, activePath]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        handleSave();
      }
      // Tab → insert 4 spaces
      if (e.key === "Tab" && document.activeElement === textareaRef.current) {
        e.preventDefault();
        const ta = textareaRef.current;
        if (ta) {
          const start = ta.selectionStart;
          const end = ta.selectionEnd;
          ta.value = ta.value.substring(0, start) + "    " + ta.value.substring(end);
          ta.selectionStart = ta.selectionEnd = start + 4;
          handleEdit(ta.value);
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handleSave, handleEdit]);

  const lineCount = activeTab?.content.split("\n").length || 1;

  return (
    <div className={cn("flex flex-col h-full bg-[var(--bg-primary)]", className)}>
      {/* Tab bar */}
      <CodeTabs
        tabs={tabs.map((t) => ({ path: t.path, name: t.name, modified: t.modified }))}
        activePath={activePath}
        onSelect={(path) => setActivePath(path)}
        onClose={closeTab}
      />

      {/* Editor */}
      {activeTab ? (
        <div className="flex-1 flex min-h-0">
          {/* Line numbers */}
          <div className="select-none text-right px-2 py-3 text-[12px] leading-[1.6] font-mono text-[var(--text-tertiary)] bg-[var(--bg-secondary)] border-r border-[var(--border)] shrink-0 overflow-hidden">
            {Array.from({ length: lineCount }, (_, i) => (
              <div key={i}>{i + 1}</div>
            ))}
          </div>

          {/* Textarea editor */}
          <textarea
            ref={textareaRef}
            value={activeTab.content}
            onChange={(e) => handleEdit(e.target.value)}
            className="flex-1 bg-transparent text-[var(--text-primary)] text-[12px] leading-[1.6] font-mono p-3 border-0 resize-none outline-none"
            style={{ tabSize: 4, whiteSpace: "pre", overflowWrap: "normal", overflowX: "auto" }}
            spellCheck={false}
          />
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center text-[var(--text-tertiary)]">
          <div className="text-center">
            <Code size={28} className="mx-auto mb-2 opacity-30" />
            <p className="text-sm">{t("codePanel.selectFile")}</p>
          </div>
        </div>
      )}

      {/* Status bar */}
      <div className="flex items-center justify-between px-3 py-1 border-t border-[var(--border)] bg-[var(--bg-secondary)] shrink-0">
        <div className="flex items-center gap-2">
          {activeTab && (
            <span className="text-[10px] font-mono text-[var(--text-tertiary)]">{activeTab.language}</span>
          )}
          {activeTab?.modified && (
            <span className="text-[10px] text-[var(--warning)]">● Modified</span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {error && (
            <span className="text-[10px] text-[var(--danger)] flex items-center gap-1">
              <AlertTriangle size={10} /> {error}
            </span>
          )}
          {activeTab?.modified && (
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] text-[var(--accent)] hover:bg-[var(--accent-bg)] transition-colors disabled:opacity-50"
            >
              <Save size={10} />
              {saving ? "Saving..." : t("common.save")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

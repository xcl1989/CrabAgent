import { useState, useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Smartphone, Monitor, Tablet, Code, Eye, Columns2, Save, RefreshCw, X } from "lucide-react";
import { cn } from "../lib/cn";
import * as filesApi from "../api/files";
import { getTree, readFile, saveFile, FileEntry } from "../api/files";

type DeviceSize = { name: string; width: number; height: number };
type ViewMode = "preview" | "source" | "split";

interface Props {
  filePath: string;
  className?: string;
  onClose?: () => void;
}

const DEVICES: DeviceSize[] = [
  { name: "📱 Phone", width: 375, height: 812 },
  { name: "💻 Desktop", width: 1280, height: 800 },
  { name: "📐 Tablet", width: 768, height: 1024 },
];

const DEVICE_LABELS: Record<string, string> = {
  "📱 Phone": "Phone",
  "💻 Desktop": "Desktop",
  "📐 Tablet": "Tablet",
};

export function PrototypePanel({ filePath, className, onClose }: Props) {
  const { t } = useTranslation();
  const [viewMode, setViewMode] = useState<ViewMode>("preview");
  const [deviceIdx, setDeviceIdx] = useState(1);
  const [source, setSource] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string>("");
  const [serverLoading, setServerLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [iframeLoading, setIframeLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const device = DEVICES[deviceIdx];

  // ── File tree state ──────────────────────────────────────
  const dir = filePath.substring(0, filePath.lastIndexOf("/")) || "/";
  const fileName = filePath.split("/").pop() || "index.html";
  const [activeFile, setActiveFile] = useState<string>(filePath);
  const [activeFileName, setActiveFileName] = useState<string>(fileName);
  const [fileEntries, setFileEntries] = useState<FileEntry[]>([]);
  const [treeLoading, setTreeLoading] = useState(false);
  const [dirty, setDirty] = useState(false);

  // Start/stop HTTP preview server on filePath change
  useEffect(() => {
    let cancelled = false;
    setServerLoading(true);
    setIframeLoading(true);
    setError(null);
    filesApi.startPreviewServer(filePath).then((res) => {
      if (!cancelled) {
        setPreviewUrl(res.url);
        setServerLoading(false);
      }
    }).catch((e: any) => {
      if (!cancelled) {
        setError(e?.message || "Failed to start preview server");
        setServerLoading(false);
      }
    });
    return () => {
      cancelled = true;
      filesApi.stopPreviewServer();
    };
  }, [filePath]);

  // Load file tree when entering source/split mode
  const loadFileTree = useCallback(async () => {
    setTreeLoading(true);
    try {
      const entries = await getTree(dir, 2, true);
      setFileEntries(entries);
    } catch {
      setFileEntries([]);
    } finally {
      setTreeLoading(false);
    }
  }, [dir]);

  // Load a specific file's content into the editor
  const loadFileContent = useCallback(async (fullPath: string, displayName: string) => {
    setLoading(true);
    setError(null);
    try {
      const result = await readFile(fullPath, true);
      setSource(result.content);
      setActiveFile(fullPath);
      setActiveFileName(displayName);
      setDirty(false);
    } catch (e: any) {
      setError(e?.message || "Failed to load file");
    } finally {
      setLoading(false);
    }
  }, []);

  // Load source only when switching to source/split mode
  const handleViewModeChange = useCallback((mode: ViewMode) => {
    setViewMode(mode);
    if ((mode === "source" || mode === "split") && !source) {
      loadFileContent(filePath, fileName);
      loadFileTree();
    }
    if (mode === "source" || mode === "split") {
      if (fileEntries.length === 0) loadFileTree();
    }
  }, [loadFileContent, loadFileTree, filePath, fileName, source, fileEntries.length]);

  // Save current file + auto-refresh iframe
  const handleSave = useCallback(async () => {
    if (!source) return;
    try {
      await saveFile(activeFile, source, true);
      setSaved(true);
      setDirty(false);
      setTimeout(() => setSaved(false), 2000);
      // Auto-refresh iframe
      setRefreshKey((k) => k + 1);
    } catch (e: any) {
      setError(e?.message || "Save failed");
    }
  }, [activeFile, source]);

  // Manual refresh iframe
  const handleRefresh = useCallback(() => {
    setIframeLoading(true);
    setRefreshKey((k) => k + 1);
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") { e.preventDefault(); handleSave(); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handleSave]);

  // Render a simple flat file list (no nested dirs for prototype)
  const renderFileList = (entries: FileEntry[], depth = 0): React.ReactNode[] => {
    const nodes: React.ReactNode[] = [];
    for (const entry of entries) {
      const isDir = entry.type === "directory";
      const isActive = activeFile === entry.path;
      const display = entry.name;
      if (isDir) {
        nodes.push(
          <div key={entry.path} className="text-[var(--text-tertiary)] text-[11px] px-2 py-0.5 font-medium" style={{ paddingLeft: 8 + depth * 12 }}>
            📁 {display}
          </div>
        );
        if (entry.children) {
          nodes.push(...renderFileList(entry.children, depth + 1));
        }
      } else {
        nodes.push(
          <button
            key={entry.path}
            onClick={() => loadFileContent(entry.path, display)}
            className={cn(
              "w-full text-left text-[11px] px-2 py-1 truncate transition-colors flex items-center gap-1.5",
              isActive
                ? "bg-[var(--brand-bg)] text-[var(--brand)]"
                : "text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
            )}
            style={{ paddingLeft: 8 + depth * 12 }}
          >
            <span className="shrink-0">{isActive ? "●" : "○"}</span>
            <span className="truncate">{display}</span>
            {dirty && isActive && <span className="text-[var(--warning)] ml-auto text-[10px]">●</span>}
          </button>
        );
      }
    }
    return nodes;
  };

  return (
    <div className={cn("flex flex-col h-full bg-[var(--bg-primary)]", className)}>
      {/* Toolbar */}
      <div className="flex items-center gap-1 px-2 py-1.5 border-b border-[var(--border)] bg-[var(--bg-secondary)] shrink-0 flex-wrap">
        <button onClick={() => handleViewModeChange("preview")} className={cn("flex items-center gap-1 px-2 py-1 rounded text-[11px]", viewMode === "preview" ? "bg-[var(--brand-bg)] text-[var(--brand)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]")}>
          <Eye size={12} /> {t("prototype.preview")}
        </button>
        <button onClick={() => handleViewModeChange("source")} className={cn("flex items-center gap-1 px-2 py-1 rounded text-[11px]", viewMode === "source" ? "bg-[var(--brand-bg)] text-[var(--brand)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]")}>
          <Code size={12} /> {t("prototype.source")}
        </button>
        <button onClick={() => handleViewModeChange("split")} className={cn("flex items-center gap-1 px-2 py-1 rounded text-[11px]", viewMode === "split" ? "bg-[var(--brand-bg)] text-[var(--brand)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]")}>
          <Columns2 size={12} /> {t("prototype.split")}
        </button>
        <div className="w-px h-4 bg-[var(--border)] mx-1" />
        {DEVICES.map((d, i) => (
          <button key={d.name} onClick={() => setDeviceIdx(i)} className={cn("px-1.5 py-1 rounded text-[11px]", i === deviceIdx ? "text-[var(--brand)] bg-[var(--brand-bg)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]")} title={d.name}>
            {DEVICE_LABELS[d.name] || d.name.split(" ")[0]}
          </button>
        ))}
        <div className="flex-1" />

        {/* Active file name indicator */}
        {(viewMode === "source" || viewMode === "split") && (
          <span className="text-[10px] text-[var(--text-tertiary)] truncate max-w-[120px] mr-1">
            {activeFileName}{dirty ? " *" : ""}
          </span>
        )}

        {/* Refresh button */}
        <button onClick={handleRefresh} className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] transition-colors" title="Reload preview">
          <RefreshCw size={12} />
        </button>

        {/* Save button with feedback */}
        <button onClick={handleSave} className={cn("flex items-center gap-1 px-2 py-1 rounded text-[11px] transition-colors", saved ? "text-[var(--success)] bg-[var(--success-bg)]" : "text-[var(--accent)] hover:bg-[var(--accent-bg)]")}>
          <Save size={12} />
          {saved ? t("common.saved") : t("common.save")}
          <span className="text-[9px] opacity-50 ml-0.5">⌘S</span>
        </button>

        {/* Close button */}
        {onClose && (
          <>
            <div className="w-px h-4 bg-[var(--border)] mx-0.5" />
            <button onClick={onClose} className="p-1 rounded text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors" title="Close">
              <X size={14} />
            </button>
          </>
        )}
      </div>

      {/* Content — keep iframe always mounted to avoid reload on view switch */}
      <div className="flex-1 min-h-0 flex">
        {/* Source pane — file tree sidebar + editor (left in split, hidden in preview) */}
        <div className={cn(
          "flex min-h-0",
          viewMode === "source" ? "flex-1" : "",
          viewMode === "preview" ? "hidden" : "",
          viewMode === "split" ? "flex-1 border-r border-[var(--border)]" : "",
        )}>
          {/* File tree sidebar */}
          <div className="w-44 shrink-0 border-r border-[var(--border)] bg-[var(--bg-secondary)] overflow-y-auto flex flex-col">
            <div className="px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)] border-b border-[var(--border)] sticky top-0 bg-[var(--bg-secondary)] z-10">
              Files
            </div>
            {treeLoading ? (
              <div className="flex items-center justify-center py-4">
                <RefreshCw size={14} className="animate-spin text-[var(--text-tertiary)]" />
              </div>
            ) : (
              <div className="py-1">{renderFileList(fileEntries)}</div>
            )}
          </div>

          {/* Editor */}
          <div className="flex-1 flex flex-col min-w-0">
            {loading ? (
              <div className="flex-1 flex items-center justify-center">
                <RefreshCw size={20} className="animate-spin text-[var(--text-tertiary)]" />
              </div>
            ) : error ? (
              <div className="flex-1 flex flex-col items-center justify-center gap-2 text-[var(--danger)]">
                <p className="text-sm">{error}</p>
                <button onClick={() => loadFileContent(activeFile, activeFileName)} className="text-xs underline hover:no-underline">Retry</button>
              </div>
            ) : (
              <textarea
                ref={editorRef}
                value={source}
                onChange={(e) => { setSource(e.target.value); setDirty(true); }}
                className="flex-1 bg-[var(--bg-primary)] text-[var(--text-primary)] text-[12px] font-mono p-3 border-0 resize-none outline-none w-full"
                spellCheck={false}
              />
            )}
          </div>
        </div>

        {/* Preview pane (right in split, hidden in source) */}
        <div className={cn(
          "flex flex-col min-h-0",
          viewMode === "preview" ? "flex-1" : "flex-1",
          viewMode === "source" ? "hidden" : "",
        )}>
          {serverLoading ? (
            <div className="flex-1 flex flex-col items-center justify-center text-[var(--text-tertiary)] gap-3">
              <RefreshCw size={28} className="animate-spin" />
              <span className="text-sm animate-pulse">{t("prototype.startingServer")}</span>
            </div>
          ) : error ? (
            <div className="flex-1 flex flex-col items-center justify-center gap-2 text-[var(--danger)]">
              <p className="text-sm">{error}</p>
            </div>
          ) : (
            <div className="flex-1 flex items-start justify-center overflow-auto p-4 bg-gray-100">
              <div className="relative" style={{ maxWidth: device.width, width: "100%" }}>
                {iframeLoading && (
                  <div className="absolute inset-0 flex items-center justify-center bg-gray-100/80 z-10">
                    <RefreshCw size={20} className="animate-spin text-[var(--text-tertiary)]" />
                  </div>
                )}
                <iframe
                  ref={iframeRef}
                  src={previewUrl ? `${previewUrl}${previewUrl.includes("?") ? "&" : "?"}_cb=${refreshKey}` : ""}
                  title="Preview"
                  className="w-full border border-gray-300 rounded bg-white"
                  style={{ height: "calc(100vh - 220px)", maxHeight: device.height }}
                  onLoad={() => setIframeLoading(false)}
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

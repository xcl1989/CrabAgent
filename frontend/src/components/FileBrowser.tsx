import { useState, useEffect } from "react";
import { PanelRightClose, X, RefreshCw, ChevronDown, ChevronRight, Search, Folder, FileText, ImageIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import i18n from "../i18n";
import { FileEntry, FileContent } from "../api/files";
import { getTree, readFile, searchFiles, isImageFile, getImageUrl } from "../api/files";
import FileTree from "./FileTree";
import MoltTimeline from "./MoltTimeline";
import GitChanges from "./GitChanges";
import { Modal } from "./ui";
import { cn } from "../lib/cn";

interface Props {
  collapsed: boolean;
  onToggle: () => void;
  sessionId: string | null;
  workspace?: string;
  onOpenDoc?: (path: string, name: string) => void;
  refreshTrigger?: number;
}

function useFileTree(workspace?: string) {
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);

  const isAbsolute = !!workspace;
  const rootPath = workspace || "";

  useEffect(() => {
    // Clear entries immediately to avoid showing stale files from previous workspace
    setEntries([]);
    setSelectedPath(null);
    setFileContent(null);
    setLoading(true);
    getTree(rootPath, 2, isAbsolute)
      .then(setEntries)
      .catch(() => setEntries([]))
      .finally(() => setLoading(false));
  }, [workspace, rootPath, isAbsolute, refreshKey]);

  const refresh = () => setRefreshKey((k) => k + 1);

  const handleSelect = async (path: string) => {
    setSelectedPath(path);
    setFileContent(null);
    setFileError(null);
    try {
      const result: FileContent = await readFile(path, isAbsolute);
      if (result.truncated) {
        setFileContent(result.message || "(truncated)");
      } else {
        setFileContent(result.content);
      }
    } catch (e: unknown) {
      setFileError(
        i18n.t("fileBrowser.readFailed"),
      );
    }
  };

  return { entries, selectedPath, fileContent, fileError, loading, handleSelect, refresh, absolute: isAbsolute };
}

// --- Collapsible Section ---
function CollapsibleSection({
  title,
  icon,
  defaultOpen = true,
  extra,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  defaultOpen?: boolean;
  extra?: React.ReactNode;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-t border-[var(--border)]">
      <div
        onClick={() => setOpen((o) => !o)}
        className="flex items-center justify-between px-2 py-1 cursor-pointer hover:bg-[var(--bg-tertiary)] transition-colors select-none"
      >
        <div className="flex items-center gap-1.5">
          {open ? (
            <ChevronDown size={11} className="text-[var(--text-tertiary)]" />
          ) : (
            <ChevronRight size={11} className="text-[var(--text-tertiary)]" />
          )}
          {icon}
          <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
            {title}
          </span>
        </div>
        {extra}
      </div>
      {open && children}
    </div>
  );
}

function FilePreview({
  selectedPath,
  fileContent,
  fileError,
  absolute,
}: {
  selectedPath: string | null;
  fileContent: string | null;
  fileError: string | null;
  absolute: boolean;
}) {
  const { t } = useTranslation();
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  if (!selectedPath) return null;

  return (
    <>
      <div className="border-t border-[var(--border)] flex flex-col" style={{ maxHeight: "30%" }}>
        <div className="p-2 text-xs font-medium truncate flex-shrink-0 text-[var(--accent)] border-b border-[var(--border)]">
          {selectedPath}
        </div>
        <div className="overflow-y-auto p-2 flex-1">
          {fileError ? (
            <div className="text-xs text-[var(--danger)]">{fileError}</div>
          ) : isImageFile(selectedPath) ? (
            <img
              src={getImageUrl(selectedPath, absolute)}
              alt={selectedPath}
              className="max-w-full max-h-[200px] object-contain rounded-lg mx-auto cursor-zoom-in"
              onClick={() => setPreviewImage(getImageUrl(selectedPath, absolute))}
            />
          ) : fileContent !== null ? (
            <pre className="text-xs leading-relaxed whitespace-pre-wrap text-[var(--text-primary)] font-mono">
              {fileContent}
            </pre>
          ) : (
            <div className="text-xs text-[var(--text-secondary)]">{t("common.loading")}</div>
          )}
        </div>
      </div>
      <Modal
        open={!!previewImage}
        onOpenChange={(o) => !o && setPreviewImage(null)}
        size="full"
        hideClose
        title={null}
      >
        <div
          className="flex items-center justify-center -mx-5 -my-4 cursor-zoom-out"
          onClick={() => setPreviewImage(null)}
          style={{ minHeight: "70vh" }}
        >
          {previewImage && (
            <img src={previewImage} alt="Preview" className="max-w-full max-h-[80vh] object-contain rounded-lg" />
          )}
        </div>
      </Modal>
    </>
  );
}

// --- File Search Results (flat list) ---
function SearchResults({
  results,
  busy,
  query,
  onSelect,
  selectedPath,
  onOpenDoc,
}: {
  results: FileEntry[];
  busy: boolean;
  query: string;
  onSelect: (path: string) => void;
  selectedPath: string | null;
  onOpenDoc?: (path: string, name: string) => void;
}) {
  const OFFICE_EXTS = [".xlsx", ".docx", ".pptx", ".html", ".md"];
  const isOffice = (name: string) => {
    const ext = name.split(".").pop()?.toLowerCase();
    return ext ? OFFICE_EXTS.includes("." + ext) : false;
  };

  if (busy) {
    return (
      <div className="text-xs p-3 text-[var(--text-secondary)] flex items-center gap-1.5">
        <RefreshCw size={11} className="animate-spin" />
        搜索中…
      </div>
    );
  }

  if (results.length === 0) {
    return (
      <div className="text-xs p-3 text-center text-[var(--text-tertiary)] italic">
        未找到匹配 "{query}" 的文件
      </div>
    );
  }

  return (
    <div>
      <div className="text-[10px] px-2 py-1 text-[var(--text-tertiary)] uppercase tracking-wider">
        {results.length} 个结果
      </div>
      {results.map((entry) => {
        const isDir = entry.type === "directory";
        const isSelected = selectedPath === entry.path;
        return (
          <div
            key={entry.path}
            onClick={() => onSelect(entry.path)}
            title={entry.path}
            className={cn(
              "group flex items-center gap-1.5 pr-2 py-1 cursor-pointer text-xs rounded-md transition-colors mx-0.5",
              isSelected
                ? "bg-[var(--brand-bg)] text-[var(--brand)]"
                : "text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
            )}
          >
            <span className="shrink-0 ml-1">
              {isDir ? (
                <Folder size={13} className="text-[var(--warning)]" />
              ) : isImageFile(entry.name) ? (
                <ImageIcon size={13} className="text-[var(--accent)]" />
              ) : (
                <FileText size={13} className="text-[var(--text-tertiary)]" />
              )}
            </span>
            <span className="flex-1 truncate">
              <span className="font-medium">{entry.name}</span>
              <span className="text-[var(--text-tertiary)] ml-1 text-[10px]">
                {entry.path.includes("/") ? entry.path.substring(0, entry.path.lastIndexOf("/")) : ""}
              </span>
            </span>
            {!isDir && onOpenDoc && isOffice(entry.name) && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onOpenDoc(entry.path, entry.name);
                }}
                className="opacity-0 group-hover:opacity-100 shrink-0 p-0.5 rounded text-[var(--accent)] hover:bg-[var(--accent-bg)] transition-all mr-1"
              >
                <FileText size={12} />
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

// --- File Search Bar ---
function FileSearchBar({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="px-2 py-1.5 border-b border-[var(--border)]">
      <div className="relative">
        <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] pointer-events-none" />
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="搜索文件… (至少2字)"
          className="w-full text-xs pl-7 pr-7 py-1.5 rounded-md border border-[var(--border)] bg-[var(--bg-primary)] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none focus:border-[var(--brand)] focus:ring-1 focus:ring-[var(--brand)]/30 transition-all"
        />
        {value && (
          <button
            onClick={() => onChange("")}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 rounded text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
          >
            <X size={12} />
          </button>
        )}
      </div>
    </div>
  );
}

export default function FileBrowser({
  collapsed,
  onToggle,
  sessionId,
  workspace,
  onOpenDoc,
  refreshTrigger,
}: Props) {
  const { t } = useTranslation();
  const tree = useFileTree(workspace);

  // ── File search ──
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<FileEntry[] | null>(null);
  const [searchBusy, setSearchBusy] = useState(false);
  const isAbsolute = !!workspace;

  // Debounced search with request cancellation
  useEffect(() => {
    const q = searchQuery.trim();
    if (q.length < 2) {
      // Need at least 2 chars — clear results and show hint for single char
      setSearchResults(null);
      setSearchBusy(false);
      return;
    }
    setSearchBusy(true);

    const controller = new AbortController();

    const timer = setTimeout(async () => {
      try {
        const results = await searchFiles(q, isAbsolute, 200, controller.signal);
        setSearchResults(results);
      } catch (err) {
        // Ignore abort errors — a newer request is in flight
        if (err instanceof DOMException && err.name === "AbortError") return;
        setSearchResults([]);
      } finally {
        // Only clear busy if this request wasn't aborted
        if (!controller.signal.aborted) {
          setSearchBusy(false);
        }
      }
    }, 150);

    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [searchQuery, isAbsolute]);

  // Auto-refresh when parent triggers (e.g. AI created/modified files)
  useEffect(() => {
    if (refreshTrigger !== undefined && refreshTrigger > 0) {
      tree.refresh();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTrigger]);

  if (collapsed) return null;

  return (
    <>
      {/* Desktop: inline sidebar */}
      <div className="hidden md:flex flex-col border-l border-[var(--border)] bg-[var(--bg-secondary)] w-80 shrink-0 overflow-y-auto">
        {/* Header */}
        <div className="p-2 flex items-center justify-between border-b border-[var(--border)]">
          <span className="text-xs font-semibold text-[var(--text-primary)]">{t("fileBrowser.files")}</span>
          <div className="flex items-center gap-0.5">
            <button
              onClick={tree.refresh}
              className="p-1 rounded text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
              title={i18n.t("fileBrowser.refresh")}
            >
              <RefreshCw size={14} />
            </button>
            <button
              onClick={onToggle}
              className="p-1 rounded text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
              title={i18n.t("fileBrowser.close")}
            >
              <PanelRightClose size={14} />
            </button>
          </div>
        </div>

        {/* Search bar */}
        <FileSearchBar value={searchQuery} onChange={setSearchQuery} />

        {/* Files / Search results */}
        <div className="overflow-y-auto" style={{ flex: "1 1 auto" }}>
          {searchResults ? (
            <SearchResults
              results={searchResults}
              busy={searchBusy}
              query={searchQuery.trim()}
              onSelect={tree.handleSelect}
              selectedPath={tree.selectedPath}
              onOpenDoc={onOpenDoc}
            />
          ) : tree.loading ? (
            <div className="text-xs p-3 text-[var(--text-secondary)]">{t("common.loading")}</div>
          ) : (
            <FileTree
              entries={tree.entries}
              onSelect={tree.handleSelect}
              selectedPath={tree.selectedPath}
              absolute={tree.absolute}
              onOpenDoc={onOpenDoc}
              onRefresh={tree.refresh}
            />
          )}
        </div>

        {/* File preview */}
        <FilePreview
          selectedPath={tree.selectedPath}
          fileContent={tree.fileContent}
          fileError={tree.fileError}
          absolute={tree.absolute}
        />

        {/* Git Changes */}
        <ErrorBoundary>
          {sessionId && <GitChanges workspace={workspace} collapsible />}
        </ErrorBoundary>

        {/* Molts */}
        <ErrorBoundary>
          {sessionId && <MoltTimeline sessionId={sessionId} collapsible />}
        </ErrorBoundary>
      </div>

      {/* Mobile: overlay drawer */}
      <div className="md:hidden">
        <div
          className="fixed inset-0 z-40 bg-[var(--bg-overlay)] backdrop-blur-sm animate-fade-in"
          onClick={onToggle}
        />
        <div className="fixed bottom-0 left-0 right-0 z-50 bg-[var(--bg-secondary)] border-t border-[var(--border)] rounded-t-2xl shadow-[var(--shadow-lg)] animate-slide-up max-h-[75vh] flex flex-col">
          <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-subtle)]">
            <span className="text-sm font-semibold text-[var(--text-primary)]">{t("fileBrowser.files")}</span>
            <div className="flex items-center gap-1">
              <button
                onClick={tree.refresh}
                className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
                title={i18n.t("fileBrowser.refresh")}
              >
                <RefreshCw size={15} />
              </button>
              <button
                onClick={onToggle}
                className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
              >
                <X size={16} />
              </button>
            </div>
          </div>
          <FileSearchBar value={searchQuery} onChange={setSearchQuery} />
          <div className="flex-1 overflow-y-auto">
            {/* Mobile: show search results or file tree */}
            {searchResults ? (
              <SearchResults
                results={searchResults}
                busy={searchBusy}
                query={searchQuery.trim()}
                onSelect={tree.handleSelect}
                selectedPath={tree.selectedPath}
                onOpenDoc={onOpenDoc}
              />
            ) : tree.loading ? (
              <div className="text-xs p-3 text-[var(--text-secondary)]">{t("common.loading")}</div>
            ) : (
              <FileTree
                entries={tree.entries}
                onSelect={tree.handleSelect}
                selectedPath={tree.selectedPath}
                absolute={tree.absolute}
                onOpenDoc={onOpenDoc}
                onRefresh={tree.refresh}
              />
            )}
            <ErrorBoundary>
              {sessionId && <GitChanges workspace={workspace} />}
            </ErrorBoundary>
            <ErrorBoundary>
              {sessionId && <MoltTimeline sessionId={sessionId} />}
            </ErrorBoundary>
          </div>
        </div>
      </div>
    </>
  );
}

// Minimal error boundary
import { Component, ReactNode } from "react";
interface EBState { hasError: boolean }
class ErrorBoundary extends Component<{ children: ReactNode }, EBState> {
  state: EBState = { hasError: false };
  static getDerivedStateFromError(): EBState { return { hasError: true }; }
  render() {
    if (this.state.hasError) return null;
    return this.props.children;
  }
}

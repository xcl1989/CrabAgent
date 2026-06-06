import { useState, useEffect } from "react";
import { PanelRightClose, X, RefreshCw, ChevronDown, ChevronRight } from "lucide-react";
import { FileEntry, FileContent } from "../api/files";
import { getTree, readFile, isImageFile, getImageUrl } from "../api/files";
import FileTree from "./FileTree";
import MoltTimeline from "./MoltTimeline";
import GitChanges from "./GitChanges";
import { Modal } from "./ui";

interface Props {
  collapsed: boolean;
  onToggle: () => void;
  sessionId: string | null;
  workspace?: string;
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
        e instanceof Error ? e.message : "Failed to read file",
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
            <div className="text-xs text-[var(--text-secondary)]">Loading...</div>
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

export default function FileBrowser({
  collapsed,
  onToggle,
  sessionId,
  workspace,
}: Props) {
  const tree = useFileTree(workspace);

  if (collapsed) return null;

  return (
    <>
      {/* Desktop: inline sidebar */}
      <div className="hidden md:flex flex-col border-l border-[var(--border)] bg-[var(--bg-secondary)] w-80 shrink-0 overflow-y-auto">
        {/* Header */}
        <div className="p-2 flex items-center justify-between border-b border-[var(--border)]">
          <span className="text-xs font-semibold text-[var(--text-primary)]">Files</span>
          <div className="flex items-center gap-0.5">
            <button
              onClick={tree.refresh}
              className="p-1 rounded text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
              title="Refresh"
            >
              <RefreshCw size={14} />
            </button>
            <button
              onClick={onToggle}
              className="p-1 rounded text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
              title="Close"
            >
              <PanelRightClose size={14} />
            </button>
          </div>
        </div>

        {/* Files */}
        <div className="overflow-y-auto" style={{ flex: "1 1 auto" }}>
          {tree.loading ? (
            <div className="text-xs p-3 text-[var(--text-secondary)]">Loading...</div>
          ) : (
            <FileTree
              entries={tree.entries}
              onSelect={tree.handleSelect}
              selectedPath={tree.selectedPath}
              absolute={tree.absolute}
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
            <span className="text-sm font-semibold text-[var(--text-primary)]">Files</span>
            <div className="flex items-center gap-1">
              <button
                onClick={tree.refresh}
                className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
                title="Refresh"
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
          <div className="flex-1 overflow-y-auto">
            {/* Mobile: simple layout without collapsible */}
            {tree.loading ? (
              <div className="text-xs p-3 text-[var(--text-secondary)]">Loading...</div>
            ) : (
              <FileTree
                entries={tree.entries}
                onSelect={tree.handleSelect}
                selectedPath={tree.selectedPath}
                absolute={tree.absolute}
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

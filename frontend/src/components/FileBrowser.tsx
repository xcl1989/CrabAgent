import { useState, useEffect } from "react";
import { PanelRightClose, X } from "lucide-react";
import { FileEntry, FileContent } from "../api/files";
import { getTree, readFile } from "../api/files";
import FileTree from "./FileTree";
import MoltTimeline from "./MoltTimeline";

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

  const isAbsolute = !!workspace;
  const rootPath = workspace || "";

  useEffect(() => {
    setLoading(true);
    getTree(rootPath, 2, isAbsolute)
      .then(setEntries)
      .catch(() => setEntries([]))
      .finally(() => setLoading(false));
  }, [workspace, rootPath, isAbsolute]);

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

  return { entries, selectedPath, fileContent, fileError, loading, handleSelect, absolute: isAbsolute };
}

function FileTreePanel({
  entries,
  selectedPath,
  fileContent,
  fileError,
  loading,
  handleSelect,
  sessionId,
  absolute,
}: {
  entries: FileEntry[];
  selectedPath: string | null;
  fileContent: string | null;
  fileError: string | null;
  loading: boolean;
  handleSelect: (path: string) => void;
  sessionId: string | null;
  absolute: boolean;
}) {
  return (
    <>
      <div className="overflow-y-auto" style={{ flex: "1 1 60%" }}>
        {loading ? (
          <div className="text-xs p-3 text-[var(--text-secondary)]">
            Loading...
          </div>
        ) : (
          <FileTree
            entries={entries}
            onSelect={handleSelect}
            selectedPath={selectedPath}
            absolute={absolute}
          />
        )}
      </div>

      {sessionId && (
        <div style={{ flex: "0 0 auto", maxHeight: "40%", overflowY: "auto" }}>
          <MoltTimeline sessionId={sessionId} />
        </div>
      )}

      {selectedPath && (
        <div
          className="border-t border-[var(--border)] flex flex-col"
          style={{ maxHeight: "40%" }}
        >
          <div className="p-2 text-xs font-medium truncate flex-shrink-0 text-[var(--accent)] border-b border-[var(--border)]">
            {selectedPath}
          </div>
          <div className="overflow-y-auto p-2 flex-1">
            {fileError ? (
              <div className="text-xs text-[var(--danger)]">{fileError}</div>
            ) : fileContent !== null ? (
              <pre className="text-xs leading-relaxed whitespace-pre-wrap text-[var(--text-primary)] font-mono">
                {fileContent}
              </pre>
            ) : (
              <div className="text-xs text-[var(--text-secondary)]">
                Loading...
              </div>
            )}
          </div>
        </div>
      )}
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
      <div className="hidden md:flex flex-col border-l border-[var(--border)] bg-[var(--bg-secondary)] w-80 shrink-0">
        <div className="p-2 flex items-center justify-between border-b border-[var(--border)]">
          <span className="text-xs font-semibold text-[var(--text-primary)]">
            Files
          </span>
          <button
            onClick={onToggle}
            className="p-1 rounded text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
            title="Collapse"
          >
            <PanelRightClose size={14} />
          </button>
        </div>
        <FileTreePanel {...tree} sessionId={sessionId} />
      </div>

      {/* Mobile: overlay drawer */}
      <div className="md:hidden">
        <div
          className="fixed inset-0 z-40 bg-[var(--bg-overlay)] backdrop-blur-sm animate-fade-in"
          onClick={onToggle}
        />
        <div className="fixed bottom-0 left-0 right-0 z-50 bg-[var(--bg-secondary)] border-t border-[var(--border)] rounded-t-2xl shadow-[var(--shadow-lg)] animate-slide-up max-h-[75vh] flex flex-col">
          <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-subtle)]">
            <span className="text-sm font-semibold text-[var(--text-primary)]">
              Files
            </span>
            <button
              onClick={onToggle}
              className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
            >
              <X size={16} />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto">
            <FileTreePanel {...tree} sessionId={sessionId} />
          </div>
        </div>
      </div>
    </>
  );
}

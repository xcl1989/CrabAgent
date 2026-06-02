import { useState, useEffect } from "react";
import { PanelRightClose } from "lucide-react";
import { FileEntry, FileContent } from "../api/files";
import { getTree, readFile } from "../api/files";
import FileTree from "./FileTree";
import MoltTimeline from "./MoltTimeline";

interface Props {
  collapsed: boolean;
  onToggle: () => void;
  sessionId: string | null;
}

export default function FileBrowser({
  collapsed,
  onToggle,
  sessionId,
}: Props) {
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getTree("", 2)
      .then(setEntries)
      .catch(() => setEntries([]))
      .finally(() => setLoading(false));
  }, []);

  const handleSelect = async (path: string) => {
    setSelectedPath(path);
    setFileContent(null);
    setFileError(null);
    try {
      const result: FileContent = await readFile(path);
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

  if (collapsed) return null;

  return (
    <div className="flex flex-col border-l border-[var(--border)] bg-[var(--bg-secondary)] w-80 shrink-0">
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
    </div>
  );
}

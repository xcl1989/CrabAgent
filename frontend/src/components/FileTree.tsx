import { useState } from "react";
import { FileEntry } from "../api/files";

interface Props {
  entries: FileEntry[];
  onSelect: (path: string) => void;
  selectedPath: string | null;
  depth?: number;
}

export default function FileTree({ entries, onSelect, selectedPath, depth = 0 }: Props) {
  if (entries.length === 0) {
    return depth === 0 ? (
      <div className="text-xs p-2" style={{ color: "var(--text-secondary)" }}>Empty directory</div>
    ) : null;
  }

  return (
    <div>
      {entries.map((entry) => (
        <FileTreeNode
          key={entry.path}
          entry={entry}
          onSelect={onSelect}
          selectedPath={selectedPath}
          depth={depth}
        />
      ))}
    </div>
  );
}

function FileTreeNode({ entry, onSelect, selectedPath, depth }: { entry: FileEntry; onSelect: (path: string) => void; selectedPath: string | null; depth: number }) {
  const [expanded, setExpanded] = useState(depth < 1);
  const [children, setChildren] = useState<FileEntry[] | undefined>(entry.children);
  const [loading, setLoading] = useState(false);
  const isDir = entry.type === "directory";
  const isSelected = selectedPath === entry.path;

  const handleToggle = async () => {
    if (!isDir) {
      onSelect(entry.path);
      return;
    }
    if (expanded) {
      setExpanded(false);
      return;
    }
    if (!children) {
      setLoading(true);
      try {
        const { getTree } = await import("../api/files");
        const result = await getTree(entry.path, 1);
        setChildren(result);
      } catch {
        setChildren([]);
      }
      setLoading(false);
    }
    setExpanded(true);
  };

  return (
    <div>
      <div
        onClick={handleToggle}
        className="flex items-center gap-1 px-2 py-1 cursor-pointer text-xs hover:opacity-80 rounded"
        style={{
          paddingLeft: 8 + depth * 14,
          background: isSelected ? "var(--bg-tertiary)" : "transparent",
          color: isSelected ? "var(--accent)" : "var(--text-primary)",
        }}
      >
        <span style={{ color: "var(--text-secondary)", width: 14, flexShrink: 0 }}>
          {isDir ? (expanded ? "▾" : "▸") : " "}
        </span>
        <span style={{ flexShrink: 0 }}>
          {isDir ? (expanded ? "📂" : "📁") : "📄"}
        </span>
        <span className="truncate">{entry.name}</span>
      </div>
      {isDir && expanded && (
        <div>
          {loading ? (
            <div className="text-xs px-2 py-1" style={{ paddingLeft: 8 + (depth + 1) * 14, color: "var(--text-secondary)" }}>
              Loading...
            </div>
          ) : (
            <FileTree entries={children || []} onSelect={onSelect} selectedPath={selectedPath} depth={depth + 1} />
          )}
        </div>
      )}
    </div>
  );
}

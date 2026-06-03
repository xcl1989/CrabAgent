import { useState } from "react";
import { Folder, FolderOpen, FileText, ChevronRight, ChevronDown, Loader2 } from "lucide-react";
import { FileEntry } from "../api/files";
import { cn } from "../lib/cn";

interface Props {
  entries: FileEntry[];
  onSelect: (path: string) => void;
  selectedPath: string | null;
  depth?: number;
  absolute?: boolean;
}

function sortEntries(entries: FileEntry[]): FileEntry[] {
  return [...entries].sort((a, b) => {
    if (a.type !== b.type) {
      return a.type === "directory" ? -1 : 1;
    }
    return a.name.localeCompare(b.name);
  });
}

export default function FileTree({
  entries,
  onSelect,
  selectedPath,
  depth = 0,
  absolute = false,
}: Props) {
  if (entries.length === 0) {
    return depth === 0 ? (
      <div className="text-xs p-3 text-center text-[var(--text-tertiary)] italic">
        Empty directory
      </div>
    ) : null;
  }

  return (
    <div>
      {sortEntries(entries).map((entry) => (
        <FileTreeNode
          key={entry.path}
          entry={entry}
          onSelect={onSelect}
          selectedPath={selectedPath}
          depth={depth}
          absolute={absolute}
        />
      ))}
    </div>
  );
}

function FileTreeNode({
  entry,
  onSelect,
  selectedPath,
  depth,
  absolute,
}: {
  entry: FileEntry;
  onSelect: (path: string) => void;
  selectedPath: string | null;
  depth: number;
  absolute: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [children, setChildren] = useState<FileEntry[] | undefined>(
    entry.children,
  );
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
        setChildren(await getTree(entry.path, 1, absolute));
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
        title={entry.path}
        className={cn(
          "flex items-center gap-1.5 pr-2 py-1 cursor-pointer text-xs rounded-md transition-colors",
          isSelected
            ? "bg-[var(--brand-bg)] text-[var(--brand)]"
            : "text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
        )}
        style={{ paddingLeft: 8 + depth * 14 }}
      >
        <span className="text-[var(--text-tertiary)] w-3 shrink-0 flex items-center">
          {isDir ? (
            expanded ? (
              <ChevronDown size={12} />
            ) : (
              <ChevronRight size={12} />
            )
          ) : (
            <span className="w-3" />
          )}
        </span>
        <span className="shrink-0">
          {isDir ? (
            expanded ? (
              <FolderOpen size={13} className="text-[var(--warning)]" />
            ) : (
              <Folder size={13} className="text-[var(--warning)]" />
            )
          ) : (
            <FileText size={13} className="text-[var(--text-tertiary)]" />
          )}
        </span>
        <span className="truncate">{entry.name}</span>
      </div>
      {isDir && expanded && (
        <div>
          {loading ? (
            <div
              className="flex items-center gap-1.5 text-xs px-2 py-1 text-[var(--text-tertiary)]"
              style={{ paddingLeft: 8 + (depth + 1) * 14 }}
            >
              <Loader2 size={11} className="animate-spin" />
              Loading…
            </div>
          ) : (
            <FileTree
              entries={children || []}
              onSelect={onSelect}
              selectedPath={selectedPath}
              depth={depth + 1}
              absolute={absolute}
            />
          )}
        </div>
      )}
    </div>
  );
}

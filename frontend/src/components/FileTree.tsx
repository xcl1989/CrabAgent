import { useState, useCallback, useEffect, useRef } from "react";
import {
  Folder,
  FolderOpen,
  FileText,
  ChevronRight,
  ChevronDown,
  Loader2,
  ImageIcon,
  ExternalLink,
  Copy,
  Download,
  Pencil,
  Trash2,
  FilePlus,
  FolderPlus,
} from "lucide-react";
import { FileEntry, isImageFile, deleteFile, renameFile, createEntry, getDownloadUrl } from "../api/files";
import { cn } from "../lib/cn";

const OFFICE_EXTS = [".xlsx", ".docx", ".pptx", ".html", ".md"];

function isOfficeFile(name: string): boolean {
  const ext = name.split(".").pop()?.toLowerCase();
  return ext ? OFFICE_EXTS.includes("." + ext) : false;
}

interface Props {
  entries: FileEntry[];
  onSelect: (path: string) => void;
  selectedPath: string | null;
  depth?: number;
  absolute?: boolean;
  onOpenDoc?: (path: string, name: string) => void;
  onRefresh?: () => void;
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
  onOpenDoc,
  onRefresh,
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
          onOpenDoc={onOpenDoc}
          onRefresh={onRefresh}
        />
      ))}
    </div>
  );
}

type ContextMenuState = {
  x: number;
  y: number;
  entry: FileEntry;
  isDir: boolean;
} | null;

type InlineEdit = {
  type: "rename" | "new-file" | "new-dir";
  parentPath?: string;
  oldName?: string;
} | null;

function FileTreeNode({
  entry,
  onSelect,
  selectedPath,
  depth,
  absolute,
  onOpenDoc,
  onRefresh,
}: {
  entry: FileEntry;
  onSelect: (path: string) => void;
  selectedPath: string | null;
  depth: number;
  absolute: boolean;
  onOpenDoc?: (path: string, name: string) => void;
  onRefresh?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [children, setChildren] = useState<FileEntry[] | undefined>(entry.children);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<InlineEdit>(null);
  const [editValue, setEditValue] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const editInputRef = useRef<HTMLInputElement>(null);
  const isDir = entry.type === "directory";
  const isSelected = selectedPath === entry.path;

  const refresh = useCallback(() => {
    if (onRefresh) {
      onRefresh();
    } else {
      // Self-refresh: reload children if expanded
      if (isDir && expanded) {
        setLoading(true);
        import("../api/files").then(({ getTree }) => {
          getTree(entry.path, 1, absolute).then((c) => {
            setChildren(c);
            setLoading(false);
          });
        });
      }
    }
  }, [onRefresh, isDir, expanded, entry.path, absolute]);

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

  // ── Context menu ──
  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();

    // Build a native-feeling custom context menu at cursor position
    const menu = buildContextMenu(
      e.clientX,
      e.clientY,
      entry,
      isDir,
      absolute,
      {
        onCopy: () => {
          navigator.clipboard.writeText(entry.path);
        },
        onDownload: () => {
          if (!isDir) {
            const url = getDownloadUrl(entry.path, absolute);
            const a = document.createElement("a");
            a.href = url;
            a.download = entry.name;
            a.click();
          }
        },
        onRename: () => {
          setEditValue(entry.name);
          setEditing({ type: "rename", oldName: entry.name });
          setTimeout(() => editInputRef.current?.select(), 0);
        },
        onDelete: () => {
          setConfirmDelete(true);
        },
        onNewFile: () => {
          setEditValue("");
          setEditing({ type: "new-file", parentPath: entry.path });
          if (!expanded) handleToggle();
          setTimeout(() => editInputRef.current?.focus(), 50);
        },
        onNewDir: () => {
          setEditValue("");
          setEditing({ type: "new-dir", parentPath: entry.path });
          if (!expanded) handleToggle();
          setTimeout(() => editInputRef.current?.focus(), 50);
        },
      },
    );
    document.body.appendChild(menu);
  };

  // ── Commit inline edit (rename / create) ──
  const commitEdit = async () => {
    if (!editing) return;
    const name = editValue.trim();
    if (!name) {
      setEditing(null);
      return;
    }

    try {
      if (editing.type === "rename") {
        const parent = entry.path.substring(0, entry.path.lastIndexOf("/") + 1);
        const newPath = absolute ? parent + name : parent + name;
        await renameFile(entry.path, newPath, absolute);
      } else if (editing.type === "new-file" || editing.type === "new-dir") {
        const parent = editing.parentPath || "";
        const newPath = parent.endsWith("/") ? parent + name : parent + "/" + name;
        await createEntry(newPath, editing.type === "new-dir" ? "directory" : "file", absolute);
      }
    } catch (e) {
      console.error("File operation failed:", e);
    }

    setEditing(null);
    refresh();
  };

  const cancelEdit = () => {
    setEditing(null);
    setEditValue("");
  };

  // ── Confirm delete ──
  const doDelete = async () => {
    setConfirmDelete(false);
    try {
      await deleteFile(entry.path, absolute);
      refresh();
    } catch (e) {
      console.error("Delete failed:", e);
    }
  };

  // ── Inline edit input ──
  if (editing && (editing.type === "rename" || expanded)) {
    const isNewItem = editing.type !== "rename";
    return (
      <div>
        {!isNewItem && (
          <div
            className="group flex items-center gap-1.5 pr-2 py-1 text-xs"
            style={{ paddingLeft: 8 + depth * 14 }}
          >
            <span className="w-3 shrink-0" />
            <span className="shrink-0">
              {isDir ? (
                <Folder size={13} className="text-[var(--warning)]" />
              ) : (
                <FileText size={13} className="text-[var(--text-tertiary)]" />
              )}
            </span>
          </div>
        )}
        <div
          className="flex items-center gap-1.5 pr-2 py-1"
          style={{ paddingLeft: 8 + (isNewItem ? (depth + 1) * 14 : depth * 14) + 16 }}
        >
          {isNewItem && (
            <span className="shrink-0">
              {editing.type === "new-dir" ? (
                <Folder size={13} className="text-[var(--warning)]" />
              ) : (
                <FileText size={13} className="text-[var(--text-tertiary)]" />
              )}
            </span>
          )}
          <input
            ref={editInputRef}
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") { e.preventDefault(); commitEdit(); }
              if (e.key === "Escape") { e.preventDefault(); cancelEdit(); }
            }}
            onBlur={() => commitEdit()}
            className="flex-1 text-xs px-1.5 py-0.5 rounded border border-[var(--brand)] bg-[var(--bg-primary)] text-[var(--text-primary)] outline-none focus:ring-2 focus:ring-[var(--brand)]/30"
          />
        </div>
      </div>
    );
  }

  return (
    <div>
      <div
        onClick={handleToggle}
        onContextMenu={handleContextMenu}
        title={entry.path}
        className={cn(
          "group flex items-center gap-1.5 pr-2 py-1 cursor-pointer text-xs rounded-md transition-colors",
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
              <Folder size={13} className="text-[var(---warning)]" />
            )
          ) : isImageFile(entry.name) ? (
            <ImageIcon size={13} className="text-[var(--accent)]" />
          ) : (
            <FileText size={13} className="text-[var(--text-tertiary)]" />
          )}
        </span>
        <span className="flex-1 truncate">{entry.name}</span>
        {!isDir && onOpenDoc && isOfficeFile(entry.name) && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onOpenDoc(entry.path, entry.name);
            }}
            className="opacity-0 group-hover:opacity-100 shrink-0 p-0.5 rounded text-[var(--accent)] hover:bg-[var(--accent-bg)] transition-all"
            title="Open in editor"
          >
            <ExternalLink size={12} />
          </button>
        )}
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
              onOpenDoc={onOpenDoc}
              onRefresh={onRefresh || refresh}
            />
          )}
        </div>
      )}

      {/* Delete confirmation */}
      {confirmDelete && (
        <DeleteConfirm
          fileName={entry.name}
          isDir={isDir}
          onConfirm={doDelete}
          onCancel={() => setConfirmDelete(false)}
        />
      )}
    </div>
  );
}

// ── Delete confirmation inline ──
function DeleteConfirm({
  fileName,
  isDir,
  onConfirm,
  onCancel,
}: {
  fileName: string;
  isDir: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--bg-overlay)] backdrop-blur-sm animate-fade-in" onClick={onCancel}>
      <div
        className="w-[320px] rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] shadow-[var(--shadow-lg)] p-4 animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-2 mb-3">
          <div className="flex items-center justify-center w-8 h-8 rounded-full bg-[var(--danger-bg)] shrink-0">
            <Trash2 size={15} className="text-[var(--danger)]" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-[var(--text-primary)]">删除{isDir ? "文件夹" : "文件"}</div>
            <div className="text-xs text-[var(--text-tertiary)] mt-0.5 truncate">
              {fileName}
            </div>
          </div>
        </div>
        <p className="text-xs text-[var(--text-secondary)] mb-4">
          {isDir ? "该文件夹及其所有内容将被删除，此操作不可撤销。" : "此操作不可撤销。"}
        </p>
        <div className="flex gap-2 justify-end">
          <button
            onClick={onCancel}
            className="px-3 py-1.5 text-xs rounded-lg text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] transition-colors"
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            className="px-3 py-1.5 text-xs rounded-lg bg-[var(--danger)] text-white hover:bg-[var(--danger-hover)] transition-colors"
          >
            删除
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Build a floating context menu ──
function buildContextMenu(
  x: number,
  y: number,
  entry: FileEntry,
  isDir: boolean,
  absolute: boolean,
  actions: {
    onCopy: () => void;
    onDownload: () => void;
    onRename: () => void;
    onDelete: () => void;
    onNewFile: () => void;
    onNewDir: () => void;
  },
): HTMLDivElement {
  const menu = document.createElement("div");
  menu.className = cn(
    "fixed z-[9999] min-w-[160px] py-1 rounded-lg",
    "border border-[var(--border)] bg-[var(--bg-elevated)] shadow-[var(--shadow-lg)]",
    "animate-scale-in origin-top-left",
  );
  menu.style.left = `${x}px`;
  menu.style.top = `${y}px`;

  // Adjust position if menu would overflow viewport
  setTimeout(() => {
    const rect = menu.getBoundingClientRect();
    if (rect.right > window.innerWidth) {
      menu.style.left = `${window.innerWidth - rect.width - 8}px`;
    }
    if (rect.bottom > window.innerHeight) {
      menu.style.top = `${window.innerHeight - rect.height - 8}px`;
    }
  }, 0);

  interface MenuItem {
    icon: React.ReactNode;
    label: string;
    action: () => void;
    danger?: boolean;
  }

  const items: MenuItem[] = [];

  if (!isDir && isOfficeFile(entry.name)) {
    items.push({
      icon: <ExternalLink size={13} />,
      label: "打开编辑",
      action: () => {},
    });
  }

  items.push({
    icon: <Copy size={13} />,
    label: "复制路径",
    action: actions.onCopy,
  });

  if (!isDir) {
    items.push({
      icon: <Download size={13} />,
      label: "下载",
      action: actions.onDownload,
    });
  }

  items.push({
    icon: <Pencil size={13} />,
    label: "重命名",
    action: actions.onRename,
  });

  if (isDir) {
    items.push({
      icon: <FilePlus size={13} />,
      label: "新建文件",
      action: actions.onNewFile,
    });
    items.push({
      icon: <FolderPlus size={13} />,
      label: "新建文件夹",
      action: actions.onNewDir,
    });
  }

  items.push({
    icon: <Trash2 size={13} />,
    label: "删除",
    action: actions.onDelete,
    danger: true,
  });

  items.forEach((item, idx) => {
    // Add separator before delete
    if (item.danger && idx > 0) {
      const sep = document.createElement("div");
      sep.className = "my-1 border-t border-[var(--border-subtle)]";
      menu.appendChild(sep);
    }

    const el = document.createElement("button");
    el.className = cn(
      "w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left transition-colors",
      item.danger
        ? "text-[var(--danger)] hover:bg-[var(--danger-bg)]"
        : "text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)]",
    );
    el.innerHTML = `<span class="shrink-0">${serializeIcon(item.icon)}</span><span>${item.label}</span>`;
    el.onclick = () => {
      item.action();
      cleanup();
    };
    menu.appendChild(el);
  });

  function cleanup() {
    menu.remove();
    document.removeEventListener("click", onDocClick);
    document.removeEventListener("contextmenu", onDocClick);
  }
  function onDocClick() {
    cleanup();
  }
  setTimeout(() => {
    document.addEventListener("click", onDocClick);
    document.addEventListener("contextmenu", onDocClick);
  }, 0);

  return menu;
}

// Render a lucide icon to HTML string for DOM menu
function serializeIcon(icon: React.ReactNode): string {
  // Simple approach: render via a temp container
  // Since these are simple SVG icons, we can just return the SVG string
  const iconMap: Record<string, string> = {
    copy: '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>',
    download: '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg>',
    pencil: '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/></svg>',
    trash: '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>',
    fileplus: '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M9 13h6"/><path d="M12 10v6"/></svg>',
    folderplus: '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/><path d="M12 10v6"/><path d="M9 13h6"/></svg>',
    external: '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>',
  };

  // Match icon to key
  const key = icon?.toString().toLowerCase() || "";
  if (key.includes("copy")) return iconMap.copy;
  if (key.includes("download")) return iconMap.download;
  if (key.includes("pencil")) return iconMap.pencil;
  if (key.includes("trash")) return iconMap.trash;
  if (key.includes("fileplus") || key.includes("file-plus")) return iconMap.fileplus;
  if (key.includes("folderplus") || key.includes("folder-plus")) return iconMap.folderplus;
  if (key.includes("external")) return iconMap.external;
  return "";
}

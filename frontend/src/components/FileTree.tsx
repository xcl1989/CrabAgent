import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Check,
  Copy,
  ExternalLink,
  FileText,
  Folder,
  FolderOpen,
  FolderPlus,
  ImageIcon,
  Pencil,
  Loader2,
  Trash2,
  X,
} from "lucide-react";
import { FileEntry, createEntry, deleteFile, getDownloadUrl, getTree, isImageFile, moveEntries, renameFile } from "../api/files";
import { cn } from "../lib/cn";

const WORKSPACE_EXTENSIONS = new Set([".xlsx", ".docx", ".pptx", ".html", ".md"]);

function opensInWorkspace(name: string): boolean {
  const dot = name.lastIndexOf(".");
  return dot >= 0 && WORKSPACE_EXTENSIONS.has(name.slice(dot).toLowerCase());
}

interface Props {
  entries: FileEntry[];
  onSelect: (path: string) => void;
  onClearSelection?: () => void;
  selectedPath: string | null;
  depth?: number;
  absolute?: boolean;
  rootPath?: string;
  onOpenDoc?: (path: string, name: string) => void;
  onRefresh?: () => void;
}

function sortEntries(entries: FileEntry[]): FileEntry[] {
  return [...entries].sort((a, b) => {
    if (a.type !== b.type) return a.type === "directory" ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
}

function joinPath(parent: string, name: string): string {
  return parent ? `${parent.replace(/\/$/, "")}/${name}` : name;
}

function parentPath(path: string): string {
  const slash = path.lastIndexOf("/");
  return slash < 0 ? "" : path.slice(0, slash);
}

export default function FileTree({
  entries,
  onSelect,
  selectedPath,
  absolute = false,
  rootPath = "",
  onClearSelection,
  onOpenDoc,
  onRefresh,
}: Props) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [creatingAt, setCreatingAt] = useState<string | null>(null);
  const [newFolderName, setNewFolderName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rootDragOver, setRootDragOver] = useState(false);
  const [activeDirectory, setActiveDirectory] = useState<string | null>(null);
  const [draggedPaths, setDraggedPaths] = useState<string[]>([]);

  const selectedPaths = useMemo(() => [...selected], [selected]);
  const refresh = useCallback(() => onRefresh?.(), [onRefresh]);

  const selectEntry = (entry: FileEntry, event: React.MouseEvent | React.DragEvent) => {
    if (entry.type === "directory") setActiveDirectory(entry.path);
    const shouldClear = !event.metaKey && !event.ctrlKey && !event.shiftKey && selected.size === 1 && selected.has(entry.path);
    if (event.metaKey || event.ctrlKey) {
      setSelected((current) => {
        const next = new Set(current);
        next.has(entry.path) ? next.delete(entry.path) : next.add(entry.path);
        return next;
      });
    } else if (event.shiftKey) {
      setSelected((current) => new Set([...current, entry.path]));
    } else {
      setSelected(shouldClear ? new Set() : new Set([entry.path]));
    }
    if (shouldClear) {
      onClearSelection?.();
    } else if (entry.type === "file") {
      onSelect(entry.path);
    }
  };

  const createFolder = async () => {
    const name = newFolderName.trim();
    if (!name || creatingAt === null) return;
    setBusy(true);
    setError(null);
    try {
      await createEntry(joinPath(creatingAt, name), "directory", absolute);
      setCreatingAt(null);
      setNewFolderName("");
      refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "新建文件夹失败");
    } finally {
      setBusy(false);
    }
  };

  const moveTo = async (destination: string) => {
    const paths = draggedPaths.length ? draggedPaths : selectedPaths;
    if (!paths.length || paths.includes(destination) || paths.every((path) => parentPath(path) === destination)) return;
    setBusy(true);
    setError(null);
    try {
      await moveEntries(paths, destination, absolute);
      setSelected(new Set());
      refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "移动失败");
    } finally {
      setBusy(false);
      setDraggedPaths([]);
    }
  };

  return (
    <div
      className={cn("pb-1", rootDragOver && "bg-[var(--brand-bg)] ring-2 ring-inset ring-[var(--brand)]")}
      onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "move"; setRootDragOver(true); }}
      onDragLeave={(event) => { if (event.currentTarget === event.target) setRootDragOver(false); }}
      onDrop={(event) => { event.preventDefault(); setRootDragOver(false); moveTo(rootPath); }}
    >
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-[var(--border)] bg-[var(--bg-secondary)] px-2 py-1 text-[10px] text-[var(--text-tertiary)] shadow-sm">
        <span>{selectedPaths.length ? `已选择 ${selectedPaths.length} 项；拖到文件夹即可移动` : "按 Cmd/Ctrl 或 Shift 多选；拖到文件夹移动"}</span>
        <div className="flex items-center gap-1">
          {selectedPaths.length > 0 && <button type="button" onClick={() => { setSelected(new Set()); onClearSelection?.(); }} className="rounded px-1 py-0.5 hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)]" title="取消选择">取消选择</button>}
          <button
            type="button"
            onClick={() => { setCreatingAt(activeDirectory ?? rootPath); setNewFolderName(""); setError(null); }}
            className="inline-flex items-center gap-1 rounded px-1 py-0.5 hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)]"
            title="新建文件夹"
          >
            <FolderPlus size={13} /> 新建
          </button>
        </div>
      </div>
      {error && <div className="mx-2 mb-1 rounded bg-[var(--danger-bg)] px-2 py-1 text-xs text-[var(--danger)]">{error}</div>}
      {creatingAt === rootPath && (
        <NewFolderInput value={newFolderName} busy={busy} onChange={setNewFolderName} onSubmit={createFolder} onCancel={() => setCreatingAt(null)} />
      )}
      {entries.length === 0 ? (
        <div className="text-xs p-3 text-center text-[var(--text-tertiary)] italic">空文件夹</div>
      ) : (
        <TreeItems
          entries={entries}
          depth={0}
          absolute={absolute}
          selected={selected}
          selectedPath={selectedPath}
          busy={busy}
          creatingAt={creatingAt}
          newFolderName={newFolderName}
          onSelect={selectEntry}
          onDragPaths={setDraggedPaths}
          onMove={moveTo}
          rootPath={rootPath}
          onCreateAt={(path) => { setCreatingAt(path); setNewFolderName(""); }}
          onCreateChange={setNewFolderName}
          onCreate={createFolder}
          onCancelCreate={() => setCreatingAt(null)}
          onDelete={async (path) => { if (confirm("确定删除此项目吗？")) { await deleteFile(path, absolute); refresh(); } }}
          onOpenDoc={onOpenDoc}
        />
      )}
    </div>
  );
}

function NewFolderInput({ value, busy, onChange, onSubmit, onCancel }: { value: string; busy: boolean; onChange: (value: string) => void; onSubmit: () => void; onCancel: () => void }) {
  return <div className="flex items-center gap-1 px-2 py-1">
    <Folder size={13} className="text-[var(--warning)] shrink-0" />
    <input autoFocus value={value} disabled={busy} onChange={(event) => onChange(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); onSubmit(); } if (event.key === "Escape") { event.preventDefault(); onCancel(); } }} placeholder="文件夹名称" className="min-w-0 flex-1 rounded border border-[var(--brand)] bg-[var(--bg-primary)] px-1.5 py-0.5 text-xs outline-none" />
    <button type="button" disabled={busy || !value.trim()} onClick={onSubmit} className="rounded p-1 text-[var(--brand)] hover:bg-[var(--brand-bg)] disabled:opacity-40" title="创建文件夹"><Check size={14} /></button>
    <button type="button" disabled={busy} onClick={onCancel} className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--danger)]" title="取消"><X size={14} /></button>
  </div>;
}

function TreeItems(props: {
  entries: FileEntry[]; depth: number; absolute: boolean; rootPath: string; selected: Set<string>; selectedPath: string | null; busy: boolean; creatingAt: string | null; newFolderName: string;
  onSelect: (entry: FileEntry, event: React.MouseEvent | React.DragEvent) => void; onDragPaths: (paths: string[]) => void; onMove: (destination: string) => void; onCreateAt: (path: string) => void; onCreateChange: (value: string) => void; onCreate: () => void; onCancelCreate: () => void; onDelete: (path: string) => void; onOpenDoc?: (path: string, name: string) => void;
}) {
  return <>{sortEntries(props.entries).map((entry) => <TreeNode key={entry.path} entry={entry} {...props} />)}</>;
}

function TreeNode({ entry, entries: _entries, depth, absolute, rootPath, selected, selectedPath, busy, creatingAt, newFolderName, onSelect, onDragPaths, onMove, onCreateAt, onCreateChange, onCreate, onCancelCreate, onDelete, onOpenDoc }: {
  entry: FileEntry; entries: FileEntry[]; depth: number; absolute: boolean; rootPath: string; selected: Set<string>; selectedPath: string | null; busy: boolean; creatingAt: string | null; newFolderName: string;
  onSelect: (entry: FileEntry, event: React.MouseEvent | React.DragEvent) => void; onDragPaths: (paths: string[]) => void; onMove: (destination: string) => void; onCreateAt: (path: string) => void; onCreateChange: (value: string) => void; onCreate: () => void; onCancelCreate: () => void; onDelete: (path: string) => void; onOpenDoc?: (path: string, name: string) => void;
}) {
  const isDir = entry.type === "directory";
  const [expanded, setExpanded] = useState(false);
  const [children, setChildren] = useState<FileEntry[] | undefined>(entry.children);
  const [loading, setLoading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState(entry.name);
  const isSelected = selected.has(entry.path) || selectedPath === entry.path;

  useEffect(() => {
    if (!menuPosition) return;
    const close = () => setMenuPosition(null);
    window.addEventListener("click", close);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [menuPosition]);

  const commitRename = async () => {
    const nextName = renameValue.trim();
    if (!nextName || nextName === entry.name) { setRenaming(false); return; }
    const parent = entry.path.slice(0, entry.path.lastIndexOf("/") + 1);
    try {
      await renameFile(entry.path, `${parent}${nextName}`, absolute);
      window.location.reload();
    } catch {
      setRenaming(false);
    }
  };

  const toggle = async () => {
    if (!isDir) return;
    if (!expanded && !children) {
      setLoading(true);
      try { setChildren(await getTree(entry.path, 1, absolute)); } finally { setLoading(false); }
    }
    setExpanded((value) => !value);
  };

  return <div>
    <div
      draggable={!busy}
      onDragStart={(event) => { onDragPaths(selected.has(entry.path) ? [...selected] : [entry.path]); event.dataTransfer.effectAllowed = "move"; }}
      onDragOver={(event) => { if (isDir && !selected.has(entry.path)) { event.preventDefault(); event.dataTransfer.dropEffect = "move"; setDragOver(true); } }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(event) => { event.preventDefault(); event.stopPropagation(); setDragOver(false); if (isDir) onMove(entry.path); }}
      onContextMenu={(event) => { event.preventDefault(); event.stopPropagation(); setMenuPosition({ x: event.clientX, y: event.clientY }); }}
      onClick={(event) => { onSelect(entry, event); if (isDir && !event.metaKey && !event.ctrlKey && !event.shiftKey) toggle(); }}
      className={cn("group flex items-center gap-1.5 py-1 pr-2 text-xs rounded-md cursor-pointer transition-colors", dragOver ? "bg-[var(--brand-bg)] text-[var(--brand)] ring-2 ring-inset ring-[var(--brand)]" : isSelected ? "bg-[var(--brand-bg)] text-[var(--brand)]" : "hover:bg-[var(--bg-tertiary)] text-[var(--text-primary)]")}
      style={{ paddingLeft: 8 + depth * 14 }}
      title={entry.path}
    >
      <span className="w-3 shrink-0 text-[var(--text-tertiary)]">{isDir ? expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} /> : null}</span>
      {isDir ? expanded ? <FolderOpen size={13} className="text-[var(--warning)] shrink-0" /> : <Folder size={13} className="text-[var(--warning)] shrink-0" /> : isImageFile(entry.name) ? <ImageIcon size={13} className="text-[var(--accent)] shrink-0" /> : <FileText size={13} className="text-[var(--text-tertiary)] shrink-0" />}
      {renaming ? <input autoFocus value={renameValue} onClick={(event) => event.stopPropagation()} onChange={(event) => setRenameValue(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") commitRename(); if (event.key === "Escape") setRenaming(false); }} onBlur={commitRename} className="min-w-0 flex-1 rounded border border-[var(--brand)] bg-[var(--bg-primary)] px-1 py-0.5 text-xs outline-none" /> : <span className="min-w-0 flex-1 truncate">{entry.name}</span>}
      {!isDir && onOpenDoc && opensInWorkspace(entry.name) && <button type="button" onClick={(event) => { event.stopPropagation(); onOpenDoc(entry.path, entry.name); }} className="hidden group-hover:inline rounded p-0.5 text-[var(--text-tertiary)] hover:bg-[var(--brand-bg)] hover:text-[var(--brand)]" title="在工作区打开"><ExternalLink size={12} /></button>}
      {isDir && <button type="button" onClick={(event) => { event.stopPropagation(); if (!expanded) toggle(); onCreateAt(entry.path); }} className="hidden group-hover:inline p-0.5 text-[var(--text-tertiary)] hover:text-[var(--brand)]" title="在此新建文件夹"><FolderPlus size={12} /></button>}
      <button type="button" onClick={(event) => { event.stopPropagation(); onDelete(entry.path); }} className="hidden group-hover:inline p-0.5 text-[var(--text-tertiary)] hover:text-[var(--danger)]" title="删除"><Trash2 size={12} /></button>
    </div>
    {menuPosition && <div className="fixed z-[100] min-w-36 rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] py-1 shadow-[var(--shadow-lg)]" style={{ left: Math.min(menuPosition.x, window.innerWidth - 176), top: Math.min(menuPosition.y, window.innerHeight - (isDir ? 180 : 150)) }} onClick={(event) => event.stopPropagation()}>
      <button type="button" onClick={async () => { try { await navigator.clipboard.writeText(entry.path); } catch { const input = document.createElement("textarea"); input.value = entry.path; input.style.position = "fixed"; input.style.opacity = "0"; document.body.appendChild(input); input.select(); document.execCommand("copy"); input.remove(); } setMenuPosition(null); }} className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-[var(--bg-tertiary)]"><Copy size={13} />复制路径</button>
      {!isDir && <button type="button" onClick={() => { const link = document.createElement("a"); link.href = getDownloadUrl(entry.path, absolute); link.download = entry.name; link.click(); setMenuPosition(null); }} className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-[var(--bg-tertiary)]"><ExternalLink size={13} />下载</button>}
      <button type="button" onClick={() => { setRenameValue(entry.name); setRenaming(true); setMenuPosition(null); }} className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-[var(--bg-tertiary)]"><Pencil size={13} />重命名</button>
      {isDir && <button type="button" onClick={() => { if (!expanded) toggle(); onCreateAt(entry.path); setMenuPosition(null); }} className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-[var(--bg-tertiary)]"><FolderPlus size={13} />新建文件夹</button>}
      <button type="button" onClick={() => { setMenuPosition(null); onDelete(entry.path); }} className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-[var(--danger)] hover:bg-[var(--danger-bg)]"><Trash2 size={13} />删除</button>
    </div>}
    {isDir && expanded && <div>
      {loading ? <div className="flex items-center gap-1 px-2 py-1 text-xs text-[var(--text-tertiary)]" style={{ paddingLeft: 22 + depth * 14 }}><Loader2 size={11} className="animate-spin" />加载中</div> : <TreeItems entries={children || []} depth={depth + 1} absolute={absolute} rootPath={rootPath} selected={selected} selectedPath={selectedPath} busy={busy} creatingAt={creatingAt} newFolderName={newFolderName} onSelect={onSelect} onDragPaths={onDragPaths} onMove={onMove} onCreateAt={onCreateAt} onCreateChange={onCreateChange} onCreate={onCreate} onCancelCreate={onCancelCreate} onDelete={onDelete} onOpenDoc={onOpenDoc} />}
      {creatingAt === entry.path && <NewFolderInput value={newFolderName} busy={busy} onChange={onCreateChange} onSubmit={onCreate} onCancel={onCancelCreate} />}
    </div>}
  </div>;
}

import { useTranslation } from "react-i18next";
import { useState, useEffect } from "react";
import { ChevronRight, ChevronDown, Folder, FolderOpen, X, Check, ArrowUp, Home } from "lucide-react";
import { FileEntry, getTree } from "../api/files";
import { cn } from "../lib/cn";

interface Props {
  open: boolean;
  onClose: () => void;
  onSelect: (path: string) => void;
}

export default function DirectoryPicker({ open, onClose, onSelect }: Props) {
  const { t } = useTranslation();
  const [currentPath, setCurrentPath] = useState("/");
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedDir, setSelectedDir] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    getTree(currentPath, 1, true)
      .then((result) => {
        setEntries(result.filter((e) => e.type === "directory"));
      })
      .catch(() => setEntries([]))
      .finally(() => setLoading(false));
  }, [currentPath, open]);

  useEffect(() => {
    if (open) {
      setCurrentPath("/");
      setSelectedDir(null);
    }
  }, [open]);

  const navigateTo = (path: string) => {
    setCurrentPath(path);
    setSelectedDir(null);
  };

  const goUp = () => {
    if (currentPath === "/") return;
    const parent = currentPath.replace(/\/[^/]+$/, "") || "/";
    navigateTo(parent);
  };

  const breadcrumbs = currentPath === "/"
    ? [{ name: "/", path: "/" }]
    : currentPath.split("/").filter(Boolean).map((seg, i, arr) => ({
        name: seg,
        path: "/" + arr.slice(0, i + 1).join("/"),
      }));

  const handleSelectDir = (path: string) => {
    setSelectedDir(path === selectedDir ? null : path);
  };

  const handleConfirm = () => {
    const path = selectedDir || currentPath;
    if (path) {
      onSelect(path);
      onClose();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") onClose();
    if (e.key === "Enter") handleConfirm();
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center"
      onKeyDown={handleKeyDown}
    >
      <div
        className="absolute inset-0 bg-black/30 backdrop-blur-sm"
        onClick={onClose}
      />
      <div
        className={cn(
          "relative z-10 w-[480px] max-h-[520px] flex flex-col",
          "bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl shadow-[var(--shadow-xl)]",
          "animate-fade-in",
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)]">
          <span className="text-sm font-semibold text-[var(--text-primary)]">
            Choose Workspace Directory
          </span>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Breadcrumbs */}
        <div className="flex items-center gap-0.5 px-3 py-2 border-b border-[var(--border)] overflow-x-auto">
          <button
            onClick={() => navigateTo("/")}
            className="shrink-0 p-0.5 rounded text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]"
            title="Root"
          >
            <Home size={13} />
          </button>
          <ChevronRight size={11} className="shrink-0 text-[var(--text-tertiary)]" />
          {breadcrumbs.map((crumb, i) => (
            <span key={crumb.path} className="flex items-center gap-0.5 shrink-0">
              <button
                onClick={() => navigateTo(crumb.path)}
                className={cn(
                  "px-1 py-0.5 rounded text-xs transition-colors",
                  i === breadcrumbs.length - 1
                    ? "text-[var(--brand)] font-medium"
                    : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
                )}
              >
                {crumb.name}
              </button>
              {i < breadcrumbs.length - 1 && (
                <ChevronRight size={11} className="text-[var(--text-tertiary)]" />
              )}
            </span>
          ))}
          <button
            onClick={goUp}
            disabled={currentPath === "/"}
            className="ml-auto shrink-0 p-1 rounded text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] disabled:opacity-30 disabled:hover:bg-transparent"
            title="Parent directory"
          >
            <ArrowUp size={13} />
          </button>
        </div>

        {/* Directory list */}
        <div className="flex-1 overflow-y-auto p-1 min-h-[200px]">
          {loading ? (
            <div className="flex items-center gap-2 px-3 py-6 text-xs text-[var(--text-tertiary)] justify-center">
              <div className="w-3.5 h-3.5 rounded-full border-2 border-[var(--brand)] border-t-transparent animate-spin" />
              Loading…
            </div>
          ) : entries.length === 0 ? (
            <div className="px-3 py-8 text-xs text-center text-[var(--text-tertiary)] italic">
              Empty directory
            </div>
          ) : (
            entries.map((entry) => (
              <button
                key={entry.path}
                onClick={() => handleSelectDir(entry.path)}
                onDoubleClick={() => navigateTo(entry.path)}
                className={cn(
                  "w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left rounded-md transition-colors",
                  selectedDir === entry.path
                    ? "bg-[var(--brand)]/10 text-[var(--brand)]"
                    : "text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]",
                )}
              >
                <span
                  onClick={(e) => {
                    e.stopPropagation();
                    navigateTo(entry.path);
                  }}
                  className="p-0.5 rounded hover:bg-[var(--bg-primary)] shrink-0 cursor-pointer"
                >
                  <ChevronRight size={12} className="text-[var(--text-tertiary)]" />
                </span>
                {selectedDir === entry.path ? (
                  <FolderOpen size={14} className="text-[var(--brand)] shrink-0" />
                ) : (
                  <Folder size={14} className="text-[var(--warning)] shrink-0" />
                )}
                <span className="truncate">{entry.name}</span>
              </button>
            ))
          )}
        </div>

        {/* Selected path + Actions */}
        <div className="flex items-center justify-between px-4 py-3 border-t border-[var(--border)]">
          <span className="text-[11px] text-[var(--text-tertiary)] truncate max-w-[320px] font-mono">
            {selectedDir || currentPath}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-3 py-1.5 text-xs rounded-md border border-[var(--border)] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleConfirm}
              className="px-3 py-1.5 text-xs rounded-md bg-[var(--brand)] text-white hover:bg-[var(--brand-active)] transition-colors flex items-center gap-1.5"
            >
              <Check size={12} />
              Select
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

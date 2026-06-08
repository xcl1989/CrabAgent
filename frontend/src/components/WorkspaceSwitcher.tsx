import { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { FolderOpen, ChevronDown, Plus, Check, Home } from "lucide-react";
import { listWorkspaces, getCurrentWorkspace, type WorkspaceInfo } from "../api/sessions";
import { cn } from "../lib/cn";
import DirectoryPicker from "./DirectoryPicker";

interface Props {
  current: string;
  onChange: (workspace: string) => void;
}

export default function WorkspaceSwitcher({ current, onChange }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);
  const [currentWorkspacePath, setCurrentWorkspacePath] = useState<string>("");
  const [showPicker, setShowPicker] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listWorkspaces().then(setWorkspaces).catch(() => {});
  }, [current]);

  useEffect(() => {
    if (open) {
      listWorkspaces().then(setWorkspaces).catch(() => {});
    }
  }, [open]);

  useEffect(() => {
    getCurrentWorkspace().then((r) => setCurrentWorkspacePath(r.workspace)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const displayName = current
    ? current.split("/").pop() || current
    : (currentWorkspacePath.split("/").pop() || currentWorkspacePath || t("workspaceSwitcher.directory"));

  const handlePickerSelect = (path: string) => {
    onChange(path);
    setOpen(false);
  };

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={cn(
          "flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium transition-colors",
          "bg-[var(--bg-tertiary)] border border-[var(--border)]",
          "hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]",
          "text-[var(--text-secondary)]",
        )}
      >
        <FolderOpen size={12} />
        <span className="truncate max-w-[120px]">{displayName}</span>
        <ChevronDown size={10} className={cn("transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div
          className={cn(
            "absolute top-full left-0 mt-1 z-50 min-w-[200px]",
            "bg-[var(--bg-secondary)] border border-[var(--border)] rounded-lg shadow-[var(--shadow-lg)]",
            "py-1 animate-fade-in",
          )}
        >
          <button
            onClick={() => {
              onChange("");
              setOpen(false);
            }}
            className={cn(
              "w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left transition-colors",
              !current
                ? "text-[var(--brand)] font-medium bg-[var(--brand)]/5"
                : "text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]",
            )}
          >
            <Home size={12} />
            <span className="flex-1 truncate" title={currentWorkspacePath}>
              {currentWorkspacePath.split("/").pop() || currentWorkspacePath || t("workspaceSwitcher.directory")}
            </span>
            {!current && <Check size={12} />}
          </button>

          {workspaces.length > 0 && (
            <div className="border-t border-[var(--border)] my-1" />
          )}

          {workspaces.map((ws) => {
            const name = ws.workspace.split("/").pop() || ws.workspace;
            const isActive = current === ws.workspace;
            return (
              <button
                key={ws.workspace}
                onClick={() => {
                  onChange(ws.workspace);
                  setOpen(false);
                }}
                className={cn(
                  "w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left transition-colors",
                  isActive
                    ? "text-[var(--brand)] font-medium bg-[var(--brand)]/5"
                    : "text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]",
                )}
              >
                <FolderOpen size={12} />
                <span className="flex-1 truncate" title={ws.workspace}>
                  {name}
                </span>
                <span
                  className={cn(
                    "inline-flex items-center justify-center min-w-[18px] h-[18px] px-1",
                    "rounded-full text-[10px] font-medium leading-none",
                    "bg-[var(--bg-tertiary)] text-[var(--text-tertiary)]",
                    isActive && "bg-[var(--brand)]/10 text-[var(--brand)]",
                  )}
                >
                  {ws.session_count}
                </span>
                {isActive && <Check size={12} />}
              </button>
            );
          })}

          <div className="border-t border-[var(--border)] my-1" />

          <button
            onClick={() => {
              setOpen(false);
              setShowPicker(true);
            }}
            className={cn(
              "w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left transition-colors",
              "text-[var(--text-tertiary)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)]",
            )}
          >
            <Plus size={12} />
            <span>{t("workspaceSwitcher.chooseDirectory")}</span>
          </button>
        </div>
      )}

      <DirectoryPicker
        open={showPicker}
        onClose={() => setShowPicker(false)}
        onSelect={handlePickerSelect}
      />
    </div>
  );
}

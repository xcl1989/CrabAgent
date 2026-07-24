import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Activity, Check, ChevronDown, Eye, EyeOff, FolderOpen, GripVertical,
  Home, Pin, Plus, Settings2, Star,
} from "lucide-react";
import {
  getCurrentWorkspace, listWorkspaces, reorderWorkspaces, updateWorkspacePreference,
  type WorkspaceInfo,
} from "../api/sessions";
import { getAgentMonitor } from "../api/monitor";
import { cn } from "../lib/cn";
import DirectoryPicker from "./DirectoryPicker";
import { Modal } from "./ui/Modal";

interface Props {
  current: string;
  onChange: (workspace: string) => void;
}

function workspaceName(workspace: string): string {
  return workspace.split("/").pop() || workspace;
}

export default function WorkspaceSwitcher({ current, onChange }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);
  const [currentWorkspacePath, setCurrentWorkspacePath] = useState("");
  const [showPicker, setShowPicker] = useState(false);
  const [showManager, setShowManager] = useState(false);
  const [activeByWorkspace, setActiveByWorkspace] = useState<Record<string, number>>({});
  const [draggedWorkspace, setDraggedWorkspace] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  const loadWorkspaces = () => listWorkspaces().then(setWorkspaces).catch(() => {});

  useEffect(() => { loadWorkspaces(); }, []);
  useEffect(() => { if (open || showManager) loadWorkspaces(); }, [open, showManager]);
  useEffect(() => { getCurrentWorkspace().then((r) => setCurrentWorkspacePath(r.workspace)).catch(() => {}); }, []);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const monitors = await getAgentMonitor();
        if (cancelled) return;
        const counts: Record<string, number> = {};
        for (const monitor of monitors) {
          if (monitor.workspace && monitor.status === "running") {
            counts[monitor.workspace] = (counts[monitor.workspace] || 0) + 1;
          }
        }
        setActiveByWorkspace(counts);
      } catch { /* Non-essential status indicator. */ }
    };
    poll();
    const interval = setInterval(poll, 5000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  useEffect(() => {
    if (!open) return;
    const handler = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const displayName = current
    ? workspaceName(current)
    : (workspaceName(currentWorkspacePath) || t("workspaceSwitcher.directory"));
  const visibleWorkspaces = workspaces.filter((workspace) => !workspace.hidden);
  const hiddenWorkspaces = workspaces.filter((workspace) => workspace.hidden);
  const totalActive = Object.values(activeByWorkspace).reduce((total, count) => total + count, 0);

  const updatePreference = async (workspace: string, update: { hidden?: boolean; pinned?: boolean }) => {
    try {
      const updated = await updateWorkspacePreference(workspace, { ...update, current_workspace: current });
      setWorkspaces((items) => items.map((item) => item.workspace === workspace ? updated : item));
    } catch { loadWorkspaces(); }
  };

  const handleDrop = async (targetWorkspace: string) => {
    if (!draggedWorkspace || draggedWorkspace === targetWorkspace) return;
    const items = [...workspaces];
    const from = items.findIndex((item) => item.workspace === draggedWorkspace);
    const to = items.findIndex((item) => item.workspace === targetWorkspace);
    if (from < 0 || to < 0) return;
    const [moved] = items.splice(from, 1);
    items.splice(to, 0, moved);
    setDraggedWorkspace(null);
    setWorkspaces(items);
    try {
      setWorkspaces(await reorderWorkspaces(items.map((item) => item.workspace)));
    } catch { loadWorkspaces(); }
  };

  const handlePickerSelect = (path: string) => {
    onChange(path);
    setOpen(false);
    setShowPicker(false);
    loadWorkspaces();
  };

  const workspaceRow = (workspace: WorkspaceInfo) => {
    const isActive = current === workspace.workspace;
    const activeCount = activeByWorkspace[workspace.workspace] || 0;
    return (
      <button
        key={workspace.workspace}
        onClick={() => { onChange(workspace.workspace); setOpen(false); }}
        className={cn(
          "w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left transition-colors",
          isActive ? "text-[var(--brand)] font-medium bg-[var(--brand)]/5" : "text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]",
        )}
      >
        {workspace.pinned ? <Pin size={12} className="text-[var(--brand)]" /> : <FolderOpen size={12} />}
        <span className="flex-1 truncate" title={workspace.workspace}>{workspaceName(workspace.workspace)}</span>
        {activeCount > 0 && <span className="inline-flex items-center gap-0.5 text-[9px] font-bold px-1.5 py-0.5 rounded-full" style={{ background: "var(--success)", color: "#fff" }}><Activity size={8} />{activeCount}</span>}
        <span className={cn("inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-medium leading-none bg-[var(--bg-tertiary)] text-[var(--text-tertiary)]", isActive && "bg-[var(--brand)]/10 text-[var(--brand)]")}>{workspace.session_count}</span>
        {isActive && <Check size={12} />}
      </button>
    );
  };

  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen(!open)} className={cn("flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium transition-colors", "bg-[var(--bg-tertiary)] border border-[var(--border)] hover:border-[var(--border-strong)] hover:text-[var(--text-primary)] text-[var(--text-secondary)]")}>
        <FolderOpen size={12} />
        <span className="truncate max-w-[120px]">{displayName}</span>
        {totalActive > 0 && <span className="inline-flex items-center justify-center min-w-[16px] h-[16px] px-1 rounded-full text-[9px] font-bold leading-none animate-pulse" style={{ background: "var(--success)", color: "#fff" }} title={`${totalActive} 个活跃会话`}>{totalActive}</span>}
        <ChevronDown size={10} className={cn("transition-transform", open && "rotate-180")} />
      </button>

      {open && <div className={cn("absolute top-full left-0 mt-1 z-50 min-w-[220px] max-w-[min(90vw,320px)]", "bg-[var(--bg-secondary)] border border-[var(--border)] rounded-lg shadow-[var(--shadow-lg)] py-1 animate-fade-in")}>
        <button onClick={() => { onChange(""); setOpen(false); }} className={cn("w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left transition-colors", !current ? "text-[var(--brand)] font-medium bg-[var(--brand)]/5" : "text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]")}>
          <Home size={12} /><span className="flex-1 truncate" title={currentWorkspacePath}>{workspaceName(currentWorkspacePath) || t("workspaceSwitcher.directory")}</span>{!current && <Check size={12} />}
        </button>
        {visibleWorkspaces.length > 0 && <div className="border-t border-[var(--border)] my-1" />}
        {visibleWorkspaces.map(workspaceRow)}
        {hiddenWorkspaces.length > 0 && <div className="px-3 pt-2 pb-1 text-[10px] text-[var(--text-tertiary)]">{t("workspaceSwitcher.hiddenCount", { count: hiddenWorkspaces.length })}</div>}
        <div className="border-t border-[var(--border)] my-1" />
        <button onClick={() => { setOpen(false); setShowPicker(true); }} className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left text-[var(--text-tertiary)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)]"><Plus size={12} /><span>{t("workspaceSwitcher.chooseDirectory")}</span></button>
        <button onClick={() => { setOpen(false); setShowManager(true); }} className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left text-[var(--text-tertiary)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)]"><Settings2 size={12} /><span>{t("workspaceSwitcher.manage")}</span></button>
      </div>}

      <DirectoryPicker open={showPicker} onClose={() => setShowPicker(false)} onSelect={handlePickerSelect} />
      <Modal open={showManager} onOpenChange={setShowManager} title={t("workspaceSwitcher.manage")} description={t("workspaceSwitcher.manageDescription")} size="lg">
        <div className="space-y-2">
          {workspaces.map((workspace) => {
            const isCurrent = workspace.workspace === current;
            return <div key={workspace.workspace} draggable onDragStart={() => setDraggedWorkspace(workspace.workspace)} onDragOver={(event) => event.preventDefault()} onDrop={() => handleDrop(workspace.workspace)} className={cn("group flex items-center gap-3 rounded-xl border px-3 py-2.5 transition-colors", draggedWorkspace === workspace.workspace ? "border-[var(--brand)] bg-[var(--brand)]/5" : "border-[var(--border-subtle)] bg-[var(--bg-tertiary)]/40")}>
              <GripVertical size={16} className="shrink-0 cursor-grab text-[var(--text-tertiary)]" />
              <FolderOpen size={15} className={workspace.hidden ? "text-[var(--text-tertiary)]" : "text-[var(--brand)]"} />
              <div className="min-w-0 flex-1"><div className="truncate text-sm font-medium text-[var(--text-primary)]" title={workspace.workspace}>{workspaceName(workspace.workspace)}</div><div className="truncate text-[11px] text-[var(--text-tertiary)]">{workspace.workspace}</div></div>
              <span className="text-[11px] text-[var(--text-tertiary)]">{workspace.session_count} {t("workspaceSwitcher.sessions")}</span>
              <span className={cn("hidden sm:inline text-[10px]", workspace.hidden ? "text-[var(--text-tertiary)]" : "text-[var(--success)]")}>{workspace.hidden ? t("workspaceSwitcher.hidden") : t("workspaceSwitcher.visible")}</span>
              <button type="button" onClick={() => updatePreference(workspace.workspace, { pinned: !workspace.pinned })} className={cn("rounded-lg p-2 transition-colors hover:bg-[var(--bg-secondary)]", workspace.pinned ? "text-[var(--brand)]" : "text-[var(--text-tertiary)]")} title={workspace.pinned ? t("workspaceSwitcher.unpin") : t("workspaceSwitcher.pin")}><Star size={15} fill={workspace.pinned ? "currentColor" : "none"} /></button>
              <button type="button" disabled={isCurrent} onClick={() => updatePreference(workspace.workspace, { hidden: !workspace.hidden })} className={cn("rounded-lg p-2 transition-colors hover:bg-[var(--bg-secondary)]", isCurrent ? "cursor-not-allowed text-[var(--border-strong)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]")} title={isCurrent ? t("workspaceSwitcher.currentProtected") : workspace.hidden ? t("workspaceSwitcher.show") : t("workspaceSwitcher.hide")}>
                {workspace.hidden ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>;
          })}
        </div>
      </Modal>
    </div>
  );
}

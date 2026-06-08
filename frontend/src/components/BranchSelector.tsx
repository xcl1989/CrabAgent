import { useState, useEffect, useRef } from "react";
import { GitBranch, ChevronDown, Play } from "lucide-react";
import * as sessionsApi from "../api/sessions";
import { BranchInfo } from "../api/sessions";
import { useTranslation } from "react-i18next";
import { cn } from "../lib/cn";

interface Props {
  sessionId: string;
  activeBranch: string;
  onSwitch: (branchId: string) => void;
  onReplay?: (branchId: string) => void;
}

export default function BranchSelector({
  sessionId,
  activeBranch,
  onSwitch,
  onReplay,
}: Props) {
  const { t } = useTranslation();
  const [branches, setBranches] = useState<BranchInfo[]>([]);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    sessionsApi.listBranches(sessionId).then(setBranches).catch(() => {});
  }, [sessionId, activeBranch]);

  // Outside click + Esc to close
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (branches.length <= 1) return null;

  return (
    <div ref={ref} className="relative flex items-center gap-1.5">
      <span className="text-[11px] text-[var(--text-tertiary)] hidden sm:inline">
        Branch
      </span>
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex items-center gap-1.5 h-7 px-2 rounded-md text-xs font-mono",
          "bg-[var(--bg-tertiary)] border border-[var(--border)]",
          "hover:border-[var(--border-strong)] transition-colors",
          open && "border-[var(--brand)]",
        )}
      >
        <GitBranch
          size={12}
          className={
            activeBranch === "main"
              ? "text-[var(--accent)]"
              : "text-[var(--warning)]"
          }
        />
        <span className="text-[var(--text-primary)]">{activeBranch}</span>
        <ChevronDown size={11} className="text-[var(--text-tertiary)]" />
      </button>

      {open && (
        <div
          className={cn(
            "absolute top-full left-0 mt-1 z-50 py-1 rounded-lg min-w-[200px]",
            "bg-[var(--bg-elevated)] border border-[var(--border)]",
            "shadow-[var(--shadow-md)] animate-scale-in origin-top-left",
          )}
        >
          {branches.map((b) => {
            const isActive = b.branch_id === activeBranch;
            return (
              <div
                key={b.branch_id}
                className={cn(
                  "flex items-center group",
                  isActive && "bg-[var(--bg-tertiary)]",
                )}
              >
                <button
                  onClick={() => {
                    onSwitch(b.branch_id);
                    setOpen(false);
                  }}
                  className="flex-1 text-left px-3 py-1.5 text-xs flex items-center gap-2"
                >
                  <GitBranch
                    size={11}
                    className={
                      b.branch_id === "main"
                        ? "text-[var(--accent)]"
                        : "text-[var(--warning)]"
                    }
                  />
                  <span
                    className={
                      isActive
                        ? "text-[var(--text-primary)] font-medium"
                        : "text-[var(--text-secondary)]"
                    }
                  >
                    {b.branch_id}
                  </span>
                  <span className="text-[10px] text-[var(--text-tertiary)] font-mono">
                    ({b.message_count})
                  </span>
                </button>
                {onReplay && b.branch_id !== activeBranch && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onReplay(b.branch_id);
                      setOpen(false);
                    }}
                    className="opacity-0 group-hover:opacity-100 p-1.5 mr-1 rounded text-[var(--text-tertiary)] hover:text-[var(--success)] hover:bg-[var(--success-bg)] transition-all"
                    title={t("branch.replay")}
                  >
                    <Play size={11} />
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

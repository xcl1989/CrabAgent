import { useTranslation } from "react-i18next";
import { useState, useEffect, useCallback } from "react";
import { RotateCcw, ChevronDown, ChevronUp, ChevronRight, Loader2, RefreshCw } from "lucide-react";
import { Molt, MoltDiff, listMolts, getMoltDiff, rollbackMolt } from "../api/sessions";
import { formatTimeShort } from "../api/time";
import { ConfirmDialog, toast, LoadingState, EmptyState } from "./ui";
import { cn } from "../lib/cn";

interface Props {
  sessionId: string;
  collapsible?: boolean;
}

export default function MoltTimeline({ sessionId, collapsible }: Props) {
  const { t } = useTranslation();
  const [molts, setMolts] = useState<Molt[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [diffData, setDiffData] = useState<MoltDiff[] | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [confirmTarget, setConfirmTarget] = useState<string | null>(null);
  const [rolling, setRolling] = useState(false);
  const [refreshing, setRefreshing] = useState(true);

  const load = useCallback(async () => {
    if (!sessionId) return;
    setRefreshing(true);
    try {
      const data = await listMolts(sessionId);
      setMolts(data);
    } catch {
      setMolts([]);
    }
    setRefreshing(false);
  }, [sessionId]);

  useEffect(() => {
    load();
  }, [load]);

  const handleToggle = async (moltId: string) => {
    if (expandedId === moltId) {
      setExpandedId(null);
      setDiffData(null);
      return;
    }
    setExpandedId(moltId);
    setDiffLoading(true);
    setDiffData(null);
    try {
      const result = await getMoltDiff(sessionId, moltId);
      setDiffData(result.diffs);
    } catch {
      setDiffData([]);
    }
    setDiffLoading(false);
  };

  const handleRollback = async (moltId: string) => {
    setRolling(true);
    try {
      const result = await rollbackMolt(sessionId, moltId);
      toast.success(t("molt.rollback"), {
        description: `${result.restored} files restored`,
      });
    } catch {
      toast.error(t("molt.rollback"));
    } finally {
      setRolling(false);
      setConfirmTarget(null);
    }
  };

  const [sectionOpen, setSectionOpen] = useState(true);

  if (refreshing && molts.length === 0) {
    return (
      <div className="border-t border-[var(--border)]">
        <div className="p-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
          Molts
        </div>
        <LoadingState compact title={t("molt.loading")} />
      </div>
    );
  }

  if (!collapsible && molts.length === 0) return null;

  return (
    <div className="border-t border-[var(--border)]">
      <div
        className={cn("flex items-center justify-between px-2 py-1", collapsible && "cursor-pointer hover:bg-[var(--bg-tertiary)] transition-colors select-none")}
        onClick={collapsible ? () => setSectionOpen((o) => !o) : undefined}
      >
        <div className="flex items-center gap-1.5">
          {collapsible && (sectionOpen ? (
            <ChevronRight size={11} className="text-[var(--text-tertiary)] rotate-90" />
          ) : (
            <ChevronRight size={11} className="text-[var(--text-tertiary)]" />
          ))}
          <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
            Molts
          </span>
          {molts.length > 0 && (
            <span className="text-[10px] text-[var(--text-tertiary)]">({molts.length})</span>
          )}
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); load(); }}
          disabled={refreshing}
          title={t("common.retry")}
          className="p-1 rounded text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
        >
          <RefreshCw size={11} className={refreshing ? "animate-spin" : ""} />
        </button>
      </div>
      {(!collapsible || sectionOpen) && molts.slice(0, 10).map((m) => {
        const expanded = expandedId === m.molt_id;
        return (
          <div key={m.molt_id}>
            <div
              onClick={() => handleToggle(m.molt_id)}
              className={cn(
                "group flex items-center justify-between gap-2 px-2 py-1.5 cursor-pointer text-xs",
                "hover:bg-[var(--bg-tertiary)] transition-colors",
              )}
            >
              <div className="flex items-center gap-1.5 min-w-0 flex-1">
                <span className="text-[var(--brand)]">🦀</span>
                <span className="truncate text-[var(--text-primary)]">
                  {m.description}
                </span>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                <span className="text-[10px] text-[var(--text-tertiary)] font-mono">
                  {formatTimeShort(m.created_at)}
                </span>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setConfirmTarget(m.molt_id);
                  }}
                  disabled={rolling}
                  title={t("molt.rollback")}
                  className={cn(
                    "p-1 rounded text-[var(--text-tertiary)] hover:text-[var(--brand)] hover:bg-[var(--brand-bg)]",
                    "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]",
                  )}
                >
                  <RotateCcw size={11} />
                </button>
                {expanded ? (
                  <ChevronUp size={12} className="text-[var(--text-tertiary)]" />
                ) : (
                  <ChevronDown size={12} className="text-[var(--text-tertiary)]" />
                )}
              </div>
            </div>
            {expanded && (
              <div className="px-3 pb-2 bg-[var(--bg-tertiary)] border-t border-[var(--border-subtle)]">
                {diffLoading ? (
                  <div className="flex items-center gap-2 py-2 text-xs text-[var(--text-tertiary)]">
                    <Loader2 size={12} className="animate-spin" />
                    Loading diff…
                  </div>
                ) : diffData && diffData.length > 0 ? (
                  diffData.map((d) => (
                    <div key={d.file} className="my-2">
                      <div className="text-[10px] font-semibold font-mono text-[var(--accent)] truncate mb-1">
                        {d.file}
                      </div>
                      <DiffViewer diff={d.diff} />
                    </div>
                  ))
                ) : (
                  <EmptyState
                    compact
                    title={t("molt.noChanges")}
                    icon={<span className="text-xs">∅</span>}
                  />
                )}
              </div>
            )}
          </div>
        );
      })}

      <ConfirmDialog
        open={!!confirmTarget}
        onOpenChange={(o) => !o && !rolling && setConfirmTarget(null)}
        title={t("molt.rollbackConfirm")}
        description={t("molt.rollbackDesc")}
        confirmText={t("molt.rollback")}
        tone="danger"
        onConfirm={() => { if (confirmTarget) handleRollback(confirmTarget); }}
      />
    </div>
  );
}

function DiffViewer({ diff }: { diff: string }) {
  const lines = diff.split("\n").slice(0, 60);
  return (
    <pre className="text-[11px] leading-snug font-mono max-h-40 overflow-auto rounded-md border border-[var(--border)] bg-[var(--code-bg)] p-0 m-0">
      {lines.map((line, i) => {
        let style: React.CSSProperties = {};
        let prefix = " ";
        if (line.startsWith("+") && !line.startsWith("+++")) {
          style = { background: "var(--success-bg)", color: "var(--success)" };
          prefix = "+";
        } else if (line.startsWith("-") && !line.startsWith("---")) {
          style = { background: "var(--danger-bg)", color: "var(--danger)" };
          prefix = "-";
        } else if (line.startsWith("@@")) {
          style = { color: "var(--accent)" };
        }
        return (
          <div key={i} className="px-2 py-px" style={style}>
            <span>{line || " "}</span>
          </div>
        );
      })}
      {diff.split("\n").length > 60 && (
        <div className="px-2 py-1 text-[10px] text-[var(--text-tertiary)] italic">
          … {diff.split("\n").length - 60} more lines truncated
        </div>
      )}
    </pre>
  );
}

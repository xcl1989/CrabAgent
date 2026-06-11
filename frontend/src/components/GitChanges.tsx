import { useTranslation } from "react-i18next";
import { useState, useEffect, useCallback } from "react";
import { GitBranch, RefreshCw, ChevronDown, ChevronUp, ChevronRight, Loader2, FilePlus, FileMinus, FilePen } from "lucide-react";
import { GitStatusResult, GitDiffResult, getGitStatus, getGitDiff } from "../api/files";
import { LoadingState, EmptyState } from "./ui";
import { cn } from "../lib/cn";

interface Props {
  workspace?: string;
  collapsible?: boolean;
}

export default function GitChanges({ workspace, collapsible }: Props) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<GitStatusResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedFile, setExpandedFile] = useState<string | null>(null);
  const [diffData, setDiffData] = useState<string>("");
  const [diffLoading, setDiffLoading] = useState(false);
  const [sectionOpen, setSectionOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getGitStatus(workspace);
      setStatus(data);
    } catch {
      setStatus(null);
    }
    setLoading(false);
  }, [workspace]);

  useEffect(() => {
    load();
  }, [load]);

  const handleToggle = async (file: string) => {
    if (expandedFile === file) {
      setExpandedFile(null);
      setDiffData("");
      return;
    }
    setExpandedFile(file);
    setDiffLoading(true);
    setDiffData("");
    try {
      const result = await getGitDiff(file, undefined, workspace);
      setDiffData(result.diff);
    } catch {
      setDiffData("");
    }
    setDiffLoading(false);
  };

  if (loading && !status) {
    return (
      <div className="border-t border-[var(--border)]">
        <div className="p-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
          Git Changes
        </div>
        <LoadingState compact title={t("git.loading")} />
      </div>
    );
  }

  if (!status || !status.is_git || status.error) return null;

  const statusIcon = (s: string) => {
    if (s.includes("A") || s.includes("?")) return <FilePlus size={11} className="text-[var(--success)]" />;
    if (s.includes("D")) return <FileMinus size={11} className="text-[var(--danger)]" />;
    if (s.includes("R")) return <FilePen size={11} className="text-[var(--accent)]" />;
    return <FilePen size={11} className="text-[var(--warning)]" />;
  };

  const statusLabel = (s: string) => {
    if (s.includes("??")) return "untracked";
    if (s.includes("A")) return "added";
    if (s.includes("D")) return "deleted";
    if (s.includes("R")) return "renamed";
    if (s.includes("M")) return "modified";
    return s;
  };

  const changes = status?.changes || [];

  return (
    <div className="border-t border-[var(--border)]">
      <div
        className={cn("flex items-center justify-between px-2 py-1", collapsible && "cursor-pointer hover:bg-[var(--bg-tertiary)] transition-colors select-none")}
        onClick={collapsible ? () => setSectionOpen((o) => !o) : undefined}
      >
        <div className="flex items-center gap-1.5">
          {collapsible && (sectionOpen ? (
            <ChevronDown size={11} className="text-[var(--text-tertiary)]" />
          ) : (
            <ChevronRight size={11} className="text-[var(--text-tertiary)]" />
          ))}
          <GitBranch size={11} className="text-[var(--accent)]" />
          <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
            Git Changes
          </span>
          {changes.length > 0 && (
            <span className="text-[10px] text-[var(--text-tertiary)]">({changes.length})</span>
          )}
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); load(); }}
          disabled={loading}
          title={t("git.refresh")}
          className="p-1 rounded text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
        >
          <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
        </button>
      </div>
      {(!collapsible || sectionOpen) && changes.slice(0, 15).map((c) => {
        const expanded = expandedFile === c.file;
        return (
          <div key={c.file}>
            <div
              onClick={() => handleToggle(c.file)}
              className={cn(
                "group flex items-center justify-between gap-2 px-2 py-1.5 cursor-pointer text-xs",
                "hover:bg-[var(--bg-tertiary)] transition-colors",
              )}
            >
              <div className="flex items-center gap-1.5 min-w-0 flex-1">
                {statusIcon(c.status)}
                <span className="truncate text-[var(--text-primary)]">
                  {c.file}
                </span>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                <span className={cn(
                  "text-[10px] px-1 py-0.5 rounded",
                  c.status.includes("??")
                    ? "bg-[var(--bg-tertiary)] text-[var(--text-tertiary)]"
                    : c.status.includes("D")
                    ? "bg-[var(--danger-bg)] text-[var(--danger)]"
                    : c.status.includes("A")
                    ? "bg-[var(--success-bg)] text-[var(--success)]"
                    : "bg-[var(--warning-bg)] text-[var(--warning)]",
                )}>
                  {statusLabel(c.status)}
                </span>
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
                ) : diffData ? (
                  <DiffViewer diff={diffData} />
                ) : (
                  <EmptyState
                    compact
                    title={t("git.noDiff")}
                    icon={<span className="text-xs">∅</span>}
                  />
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function DiffViewer({ diff }: { diff: string }) {
  const lines = diff.split("\n").slice(0, 60);
  return (
    <pre className="text-[11px] leading-snug font-mono max-h-40 overflow-auto rounded-md border border-[var(--border)] bg-[var(--code-bg)] p-0 m-0">
      {lines.map((line, i) => {
        let style: React.CSSProperties = {};
        if (line.startsWith("+") && !line.startsWith("+++")) {
          style = { background: "var(--success-bg)", color: "var(--success)" };
        } else if (line.startsWith("-") && !line.startsWith("---")) {
          style = { background: "var(--danger-bg)", color: "var(--danger)" };
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

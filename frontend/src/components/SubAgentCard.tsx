/**
 * SubAgentCard — a timeline-style card for sub-agent activities.
 *
 * Default: one-line summary (agent icon + name + task + stats).
 * Click:   inline expand showing the live timeline (text/tool_call/tool_result).
 * Double:  optional "view full" → opens the existing Modal.
 */

import { memo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Search,
  Sparkles,
  Terminal,
  FileText,
  ListChecks,
  Bot,
  ChevronRight,
  CheckCircle2,
  Loader2,
  AlertTriangle,
  Zap,
  Clock,
  Layers,
  Cpu,
} from "lucide-react";
import { cn } from "../lib/cn";

// ── Agent icon & color mapping ──────────────────────────────────────────

export const AGENT_ICONS: Record<string, React.ReactNode> = {
  researcher: <Search size={13} />,
  analyst: <Sparkles size={13} />,
  coder: <Terminal size={13} />,
  writer: <FileText size={13} />,
  plan_creater: <ListChecks size={13} />,
};

/** Returns the CSS var name for the agent's theme color, or undefined. */
export function agentColorVar(name?: string): string | undefined {
  if (!name) return undefined;
  return `var(--agent-${name})`;
}

// ── Segments (parsed from the live content stream) ──────────────────────

export interface SubAgentSegment {
  type: "text" | "tool_call" | "tool_result";
  content: string;
  name?: string;
}

export function parseSubAgentContent(raw: string): SubAgentSegment[] {
  const segments: SubAgentSegment[] = [];
  let remaining = raw;
  while (remaining.length > 0) {
    const callIdx = remaining.indexOf("\n→ ");
    const resultIdx = remaining.indexOf("\n← ");
    const nextSpecial = Math.min(
      callIdx >= 0 ? callIdx : Infinity,
      resultIdx >= 0 ? resultIdx : Infinity,
    );
    if (nextSpecial === Infinity) {
      if (remaining.trim()) {
        segments.push({ type: "text", content: remaining.trim() });
      }
      break;
    }
    if (nextSpecial > 0) {
      const textPart = remaining.slice(0, nextSpecial).trim();
      if (textPart) segments.push({ type: "text", content: textPart });
    }
    const isCall = callIdx >= 0 && (resultIdx < 0 || callIdx <= resultIdx);
    const marker = isCall ? "\n→ " : "\n← ";
    const start = remaining.indexOf(marker);
    const end = remaining.indexOf("\n→ ", start + 1);
    const end2 = remaining.indexOf("\n← ", start + 1);
    const blockEnd = Math.min(
      end >= 0 ? end : Infinity,
      end2 >= 0 ? end2 : Infinity,
    );
    const block =
      blockEnd === Infinity
        ? remaining.slice(start + marker.length)
        : remaining.slice(start + marker.length, blockEnd);
    if (isCall) {
      const colonIdx = block.indexOf("(");
      const name = colonIdx >= 0 ? block.slice(0, colonIdx) : block;
      const args = colonIdx >= 0 ? block.slice(colonIdx) : "()";
      segments.push({ type: "tool_call", content: args, name: name.trim() });
    } else {
      const colonIdx = block.indexOf(":");
      const name = colonIdx >= 0 ? block.slice(0, colonIdx) : "";
      const result = colonIdx >= 0 ? block.slice(colonIdx + 1) : block;
      segments.push({
        type: "tool_result",
        content: result.trim(),
        name: name.trim(),
      });
    }
    remaining =
      blockEnd === Infinity ? "" : remaining.slice(blockEnd);
  }
  return segments;
}

// ── Stat badge ───────────────────────────────────────────────────────────

function StatBadge({ icon, label, kind }: { icon?: React.ReactNode; label: string; kind?: "model" }) {
  return (
    <span className={cn("subagent-stat-badge", kind === "model" && "subagent-stat-badge--model")}>
      {icon}
      {label}
    </span>
  );
}

// ── Timeline body (expanded view) ────────────────────────────────────────

const TimelineBody = memo(function TimelineBody({ content }: { content: string }) {
  const segments = parseSubAgentContent(content);
  if (segments.length === 0) {
    return (
      <div className="flex items-center justify-center gap-2 py-4 text-xs text-[var(--text-tertiary)]">
        <Loader2 size={12} className="animate-spin" />
        <span>working…</span>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1.5 py-1">
      {segments.map((seg, i) => {
        if (seg.type === "text") {
          return (
            <div key={i} className="subagent-timeline-entry">
              <div className="text-xs whitespace-pre-wrap leading-relaxed text-[var(--text-secondary)]">
                {seg.content}
              </div>
            </div>
          );
        }
        if (seg.type === "tool_call") {
          return (
            <div key={i} className="subagent-timeline-entry">
              <div className="flex items-center gap-1.5 py-0.5 text-[11px]">
                <Zap size={10} className="text-[var(--accent-2)] shrink-0" />
                <span className="font-medium text-[var(--accent-2)] shrink-0">
                  {seg.name}
                </span>
                <span className="text-[var(--text-tertiary)] font-mono truncate">
                  {seg.content}
                </span>
              </div>
            </div>
          );
        }
        if (seg.type === "tool_result") {
          return (
            <div key={i} className="subagent-timeline-entry">
              <div className="rounded-md border-l-2 border-l-[var(--success)] bg-[var(--bg-tertiary)] overflow-hidden">
                <div className="px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-[var(--success)] flex items-center gap-1">
                  <CheckCircle2 size={9} /> {seg.name || "result"}
                </div>
                <pre className="px-2 py-1 text-[11px] whitespace-pre-wrap break-all leading-relaxed font-mono text-[var(--text-tertiary)] m-0 max-h-32 overflow-auto bg-transparent border-0">
                  {seg.content}
                </pre>
              </div>
            </div>
          );
        }
        return null;
      })}
    </div>
  );
});

// ── Main card ────────────────────────────────────────────────────────────

export interface SubAgentCardProps {
  agentName?: string;
  agentDisplay?: string;
  task?: string;
  status: "running" | "completed" | "error";
  model?: string;
  iterations?: number;
  elapsed?: number;
  tokens?: number;
  /** The raw live-streamed or persisted content (text + tool calls). */
  content: string;
  /** Controlled expanded state (optional). Uncontrolled when omitted. */
  expanded?: boolean;
  onToggleExpand?: () => void;
  onClick?: () => void;
  isActive?: boolean;
  /** Show the vertical connector line below this card (pipeline mode). */
  showConnector?: boolean;
}

export const SubAgentCard = memo(function SubAgentCard({
  agentName,
  agentDisplay,
  task,
  status,
  model,
  iterations,
  elapsed,
  tokens,
  content,
  expanded,
  onToggleExpand,
  onClick,
  isActive,
  showConnector,
}: SubAgentCardProps) {
  const { t } = useTranslation();
  const [internalExpanded, setInternalExpanded] = useState(false);
  const isExpanded = expanded !== undefined ? expanded : internalExpanded;

  const handleToggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (onToggleExpand) {
      onToggleExpand();
    } else {
      setInternalExpanded((v) => !v);
    }
  };

  const handleClick = () => {
    onClick?.();
  };

  const agentIcon = AGENT_ICONS[agentName || ""] || <Bot size={13} />;
  const colorVar = agentColorVar(agentName);

  const statusIcon =
    status === "completed" ? (
      <CheckCircle2 size={12} className="text-[var(--success)] shrink-0" />
    ) : status === "error" ? (
      <AlertTriangle size={12} className="text-[var(--danger)] shrink-0" />
    ) : (
      <Loader2 size={11} className="animate-spin text-[var(--accent-2)] shrink-0" />
    );

  const statusLabel =
    status === "completed"
      ? t("subAgent.completed")
      : status === "error"
        ? t("subAgent.failed")
        : t("subAgent.running");

  return (
    <>
      <div
        onClick={handleClick}
        className={cn(
          "subagent-card group rounded-lg bg-[var(--bg-secondary)] border border-[var(--border)] cursor-pointer transition-all",
          isActive && "subagent-card--active",
        )}
        style={
          colorVar
            ? ({
                borderColor: isActive ? colorVar : undefined,
                ["--agent-color" as string]: colorVar,
                ["--agent-color-bg" as string]: `var(--agent-${agentName}-bg)`,
              } as React.CSSProperties)
            : undefined
        }
      >
        {/* Header — always visible (the "one-line summary") */}
        <div className="flex items-center gap-2 px-3 py-2">
          <span
            className="shrink-0 flex items-center justify-center w-5 h-5 rounded-full"
            style={{ background: colorVar ? `var(--agent-${agentName}-bg)` : "var(--bg-tertiary)", color: colorVar || "var(--text-secondary)" }}
          >
            {agentIcon}
          </span>
          <div className="flex-1 min-w-0 flex items-center gap-1.5">
            <span className="font-medium text-xs text-[var(--text-primary)] truncate">
              {agentDisplay || agentName || "Agent"}
            </span>
            <span className="text-[10px] text-[var(--text-tertiary)]">·</span>
            <span className="text-[10px] text-[var(--text-tertiary)] truncate">{statusLabel}</span>
            {task && (
              <span className="text-[10px] text-[var(--text-tertiary)] truncate hidden sm:inline">
                — {task}
              </span>
            )}
          </div>
          {statusIcon}
          {/* Stats badges */}
          <div className="hidden md:flex items-center gap-1">
            {iterations !== undefined && status === "completed" && (
              <StatBadge icon={<Layers size={9} />} label={`${iterations}`} />
            )}
            {elapsed !== undefined && status === "completed" && (
              <StatBadge icon={<Clock size={9} />} label={`${elapsed}s`} />
            )}
            {tokens !== undefined && status === "completed" && tokens > 0 && (
              <StatBadge label={tokens > 999 ? `${(tokens / 1000).toFixed(1)}k` : `${tokens}`} />
            )}
            {model && (
              <StatBadge icon={<Cpu size={9} />} label={model} kind="model" />
            )}
          </div>
          <ChevronRight
            size={12}
            className={cn(
              "shrink-0 text-[var(--text-tertiary)] transition-transform",
              isExpanded && "rotate-90",
            )}
            onClick={handleToggle}
          />
        </div>

        {/* Expanded timeline */}
        {isExpanded && (
          <div className="px-3 pb-2 border-t border-[var(--border)]">
            <TimelineBody content={content} />
          </div>
        )}
      </div>
      {showConnector && <div className="subagent-card__connector" />}
    </>
  );
});

// ── Delegate group (wrapper for pipeline/parallel/sequential) ────────────

export interface DelegateGroupProps {
  mode: "single" | "pipeline" | "parallel";
  children: React.ReactNode;
  title?: string;
}

export function DelegateGroup({ mode, children, title }: DelegateGroupProps) {
  const { t } = useTranslation();
  const label =
    mode === "pipeline"
      ? title || t("subAgent.pipeline")
      : mode === "parallel"
        ? title || t("subAgent.parallel")
        : title || t("subAgent.delegation");

  return (
    <div className="mb-3 ml-3">
      <div className="flex items-center gap-1.5 px-1 mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
        <span className="w-3 h-px bg-[var(--border-strong)]" />
        {label}
      </div>
      <div className={cn(mode === "parallel" && "grid grid-cols-1 lg:grid-cols-2 gap-2")}>
        {children}
      </div>
    </div>
  );
}

import { useCallback, useEffect, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Cpu,
  Wrench,
  Users,
  AlertCircle,
  Clock,
  Coins,
  Zap,
  AlertTriangle,
  Info,
} from "lucide-react";
import { cn } from "../lib/cn";
import {
  getSessionSpanTrees,
  getSessionInsights,
  type SpanNode,
  type RunSummary,
  type Insight,
} from "../api/execution";

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatTime(ts: number): string {
  if (!ts) return "";
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(ts * 1000));
}

// ── Span type visual config ──
const SPAN_CONFIG: Record<
  string,
  { icon: typeof Cpu; color: string; bg: string }
> = {
  agent_run: { icon: Zap, color: "var(--brand)", bg: "var(--brand-bg)" },
  llm_call: { icon: Cpu, color: "var(--accent)", bg: "transparent" },
  tool_call: { icon: Wrench, color: "var(--success)", bg: "transparent" },
  agent_delegate: { icon: Users, color: "var(--warning)", bg: "transparent" },
  compress: { icon: AlertCircle, color: "var(--accent-2)", bg: "transparent" },
};

function SpanRow({
  node,
  totalRunTokens,
  depth,
}: {
  node: SpanNode;
  totalRunTokens: number;
  depth: number;
}) {
  const [expanded, setExpanded] = useState(true);
  const [showDetail, setShowDetail] = useState(false);
  const config = SPAN_CONFIG[node.span_type] ?? SPAN_CONFIG.llm_call;
  const Icon = config.icon;
  const hasChildren = node.children && node.children.length > 0;
  const totalTokens = node.prompt_tokens + node.completion_tokens;
  const tokenShare = totalRunTokens > 0 ? totalTokens / totalRunTokens : 0;
  const isError = node.status === "error";
  const isSlow = node.duration_ms > 10_000;

  return (
    <>
      <div
        className="flex items-center gap-1.5 py-1 hover:bg-[var(--bg-tertiary)]/50 rounded cursor-pointer text-xs"
        style={{ paddingLeft: depth * 20 + 4 }}
        onClick={() => setShowDetail(!showDetail)}
      >
        {/* Expand toggle */}
        <button
          className={cn(
            "shrink-0 w-4 h-4 flex items-center justify-center",
            !hasChildren && "invisible",
          )}
          onClick={(e) => {
            e.stopPropagation();
            setExpanded(!expanded);
          }}
        >
          {expanded ? (
            <ChevronDown size={12} className="text-[var(--text-tertiary)]" />
          ) : (
            <ChevronRight size={12} className="text-[var(--text-tertiary)]" />
          )}
        </button>

        {/* Icon */}
        <Icon
          size={13}
          className={cn(
            "shrink-0",
            isError ? "text-[var(--danger)]" : "",
          )}
          style={{ color: isError ? undefined : config.color }}
        />

        {/* Name */}
        <span
          className={cn(
            "font-medium truncate",
            isError ? "text-[var(--danger)]" : "text-[var(--text-primary)]",
          )}
        >
          {node.name}
        </span>

        {/* Provider badge (llm_call only) */}
        {node.span_type === "llm_call" && node.provider && (
          <span className="shrink-0 px-1.5 py-0.5 rounded text-[9px] font-mono bg-[var(--bg-tertiary)] text-[var(--text-tertiary)]">
            {node.provider}
          </span>
        )}

        {/* Token share bar */}
        {totalTokens > 0 && (
          <div className="shrink-0 flex items-center gap-1">
            <div className="w-16 h-1 rounded-full bg-[var(--bg-tertiary)] overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.max(tokenShare * 100, 3)}%`,
                  background: config.color,
                }}
              />
            </div>
            <span className="text-[10px] font-mono text-[var(--text-tertiary)]">
              {formatTokens(totalTokens)}
            </span>
          </div>
        )}

        {/* Duration */}
        <span
          className={cn(
            "shrink-0 text-[10px] font-mono ml-auto",
            isSlow ? "text-[var(--danger)]" : "text-[var(--text-tertiary)]",
          )}
        >
          <Clock size={9} className="inline mr-0.5" />
          {formatDuration(node.duration_ms)}
        </span>
      </div>

      {/* Detail row */}
      {showDetail && (
        <div
          className="py-1.5 px-3 mb-1 rounded-lg bg-[var(--bg-tertiary)]/40 border border-[var(--border-subtle)] text-[11px] space-y-1"
          style={{ marginLeft: depth * 20 + 24 }}
        >
          <div className="flex gap-4 text-[var(--text-tertiary)]">
            <span>⏱ {formatTime(node.started_at)}</span>
            {node.agent_name && <span>🤖 {node.agent_name}</span>}
            {node.provider && <span>🔌 {node.provider}</span>}
            {node.source && <span>📦 {node.source}</span>}
          </div>
          {(node.prompt_tokens > 0 || node.completion_tokens > 0) && (
            <div className="flex gap-3 text-[var(--text-secondary)]">
              <Coins size={11} className="text-[var(--warning)] mt-0.5" />
              <span>in: {formatTokens(node.prompt_tokens)}</span>
              {node.cached_tokens > 0 && (
                <span className="text-[var(--success)]">
                  cached: {formatTokens(node.cached_tokens)}
                </span>
              )}
              <span>out: {formatTokens(node.completion_tokens)}</span>
              {node.reasoning_tokens > 0 && (
                <span className="text-[var(--accent-2)]">
                  reasoning: {formatTokens(node.reasoning_tokens)}
                </span>
              )}
            </div>
          )}
          {node.summary && (
            <p className="text-[var(--text-secondary)] leading-relaxed line-clamp-3">
              {node.summary}
            </p>
          )}
          {node.error && (
            <p className="text-[var(--danger)] leading-relaxed">{node.error}</p>
          )}
        </div>
      )}

      {/* Children */}
      {expanded &&
        hasChildren &&
        node.children.map((child) => (
          <SpanRow
            key={child.id}
            node={child}
            totalRunTokens={totalRunTokens}
            depth={depth + 1}
          />
        ))}
    </>
  );
}

function RunBlock({
  runId,
  tree,
  runs,
}: {
  runId: string;
  tree: SpanNode[];
  runs: RunSummary[];
}) {
  const runInfo = runs.find((r) => r.run_id === runId);
  const totalTokens = runInfo?.total_tokens ?? 0;

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--border-subtle)] bg-[var(--bg-tertiary)]/40">
        <Zap size={14} className="text-[var(--brand)]" />
        <span className="text-xs font-semibold">
          {runInfo?.agent_name || "agent"} · {formatTime(runInfo?.started_at ?? 0)}
        </span>
        {totalTokens > 0 && (
          <span className="text-[11px] text-[var(--text-tertiary)] font-mono ml-auto">
            {formatTokens(totalTokens)} tok · {(runInfo?.span_count ?? 0)} steps
          </span>
        )}
      </div>
      <div className="py-1.5 px-2">
        {tree.map((node) => (
          <SpanRow
            key={node.id}
            node={node}
            totalRunTokens={totalTokens}
            depth={0}
          />
        ))}
      </div>
    </div>
  );
}

export default function ExecutionTreePanel({ sessionId }: { sessionId: string }) {
  const [loading, setLoading] = useState(true);
  const [trees, setTrees] = useState<Record<string, SpanNode[]>>({});
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [insights, setInsights] = useState<Insight[]>([]);
  const [error, setError] = useState("");

  const fetchSpans = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    setError("");
    try {
      const [spanData, runData, insightData] = await Promise.all([
        getSessionSpanTrees(sessionId),
        import("../api/execution").then((m) => m.getSessionRuns(sessionId)),
        getSessionInsights(sessionId).catch(() => ({ session_id: sessionId, insights: [] })),
      ]);
      setTrees(spanData.trees);
      setRuns(runData.runs);
      setInsights(insightData.insights || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load execution data");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void fetchSpans();
  }, [fetchSpans]);

  const runIds = Object.keys(trees);

  if (loading) {
    return (
      <div className="py-12 text-center text-sm text-[var(--text-tertiary)]">
        Loading execution tree...
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-8 text-center text-sm text-[var(--danger)]">{error}</div>
    );
  }

  if (runIds.length === 0) {
    return (
      <div className="py-12 text-center text-sm text-[var(--text-tertiary)]">
        No execution data yet. Run a task to see the trace.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Insights */}
      {insights.length > 0 && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] overflow-hidden">
          <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--border-subtle)] bg-[var(--bg-tertiary)]/40">
            <AlertTriangle size={14} className="text-[var(--warning)]" />
            <span className="text-xs font-semibold">
              {insights.length} 条洞察
            </span>
          </div>
          <div className="divide-y divide-[var(--border-subtle)]">
            {insights.map((insight, i) => {
              const Icon =
                insight.severity === "error"
                  ? AlertCircle
                  : insight.severity === "warning"
                    ? AlertTriangle
                    : Info;
              const color =
                insight.severity === "error"
                  ? "var(--danger)"
                  : insight.severity === "warning"
                    ? "var(--warning)"
                    : "var(--accent)";
              return (
                <div key={i} className="px-3 py-2 flex gap-2 text-xs">
                  <Icon size={14} className="shrink-0 mt-0.5" style={{ color }} />
                  <div className="min-w-0">
                    <p className="font-medium text-[var(--text-primary)]">
                      {insight.title}
                    </p>
                    <p className="text-[var(--text-tertiary)] mt-0.5 leading-relaxed">
                      {insight.detail}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Run trees */}
      {runIds.map((runId) => (
        <RunBlock
          key={runId}
          runId={runId}
          tree={trees[runId]}
          runs={runs}
        />
      ))}
    </div>
  );
}

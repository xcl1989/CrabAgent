import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import {
  Bar,
  BarChart,
  Cell,
  ComposedChart,
  Legend,
  Line,
  Pie,
  PieChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { MeasuredChartContainer } from "../components/charts/MeasuredChartContainer";
import { ChevronDown, ChevronRight, Coins, TrendingUp, Zap, Database, BarChart3, PieChart as PieIcon, RefreshCw } from "lucide-react";
import { cn } from "../lib/cn";
import {
  getOverview,
  getSessionsUsage,
  getSessionUsageDetail,
  getWorkspacesUsage,
  type TokenUsageOverview,
  type SessionUsage,
  type SessionUsageDetail,
  type WorkspaceUsage,
} from "../api/tokenUsage";

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

const PIE_COLORS = ["var(--brand)", "#6366f1", "#8b5cf6", "#ec4899", "#f59e0b", "#10b981", "#06b6d4"];

export default function UsagePage() {
  const { t } = useTranslation();
  const [days, setDays] = useState(30);
  const [workspace, setWorkspace] = useState("");
  const [overview, setOverview] = useState<TokenUsageOverview | null>(null);
  const [sessions, setSessions] = useState<SessionUsage[]>([]);
  const [sessionsTotal, setSessionsTotal] = useState(0);
  const [workspaces, setWorkspaces] = useState<WorkspaceUsage[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedSession, setExpandedSession] = useState<string | null>(null);
  const [sessionDetail, setSessionDetail] = useState<SessionUsageDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [ov, sess] = await Promise.all([
        getOverview(days, workspace),
        getSessionsUsage(50, 0, workspace),
      ]);
      setOverview(ov);
      setSessions(sess.sessions);
      setSessionsTotal(sess.total);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [days, workspace]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Load workspace list once
  useEffect(() => {
    getWorkspacesUsage().then(setWorkspaces).catch(() => {});
  }, []);

  const handleExpand = async (sessionId: string) => {
    if (expandedSession === sessionId) {
      setExpandedSession(null);
      setSessionDetail(null);
      return;
    }
    setExpandedSession(sessionId);
    setDetailLoading(true);
    try {
      const detail = await getSessionUsageDetail(sessionId);
      setSessionDetail(detail);
    } catch {
      setSessionDetail(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const rangeOptions = [
    { days: 1, label: t("usage.rangeToday") },
    { days: 7, label: t("usage.range7d") },
    { days: 30, label: t("usage.range30d") },
    { days: 365, label: t("usage.rangeAll") },
  ];

  const wsLabel = (ws: string): string => {
    const parts = ws.split("/");
    return parts[parts.length - 1] || ws;
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-6 space-y-6">
        {/* Header + Filters */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <h1 className="text-xl font-bold text-[var(--text-primary)] flex items-center gap-2 shrink-0">
            <Coins size={20} className="text-[var(--brand)]" />
            {t("usage.title")}
          </h1>
          <div className="flex items-center gap-3 flex-wrap">
            {/* Workspace filter */}
            <select
              value={workspace}
              onChange={(e) => setWorkspace(e.target.value)}
              className={cn(
                "text-xs font-medium px-3 py-1.5 rounded-lg border border-[var(--border)]",
                "bg-[var(--bg-secondary)] text-[var(--text-secondary)]",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]",
              )}
            >
              <option value="">{t("usage.allProjects")}</option>
              {workspaces.map((ws) => (
                <option key={ws.workspace} value={ws.workspace}>
                  {wsLabel(ws.workspace)} ({formatTokens(ws.total_tokens)})
                </option>
              ))}
            </select>
            {/* Refresh */}
            <button
              onClick={fetchData}
              disabled={loading}
              title={t("usage.refresh")}
              className={cn(
                "p-1.5 rounded-lg transition-colors",
                "text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
                loading && "opacity-50 pointer-events-none",
              )}
            >
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            </button>
            {/* Range toggle */}
            <div className="flex gap-1 bg-[var(--bg-tertiary)] rounded-lg p-0.5">
              {rangeOptions.map((opt) => (
                <button
                  key={opt.days}
                  onClick={() => setDays(opt.days)}
                  className={cn(
                    "px-3 py-1 text-xs font-medium rounded-md transition-all",
                    days === opt.days
                      ? "bg-[var(--brand)] text-white"
                      : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {loading ? (
          <div className="text-center py-20 text-[var(--text-tertiary)]">{t("common.loading")}</div>
        ) : !overview || overview.total_calls === 0 ? (
          <div className="text-center py-20 text-[var(--text-tertiary)]">{t("usage.noData")}</div>
        ) : (
          <>
            {/* Overview Cards */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <StatCard
                icon={<TrendingUp size={16} />}
                label={t("usage.totalTokens")}
                value={formatTokens(overview.total_tokens)}
                sub={`${formatTokens(overview.prompt_tokens)} + ${formatTokens(overview.completion_tokens)}`}
              />
              <StatCard
                icon={<Zap size={16} />}
                label={t("usage.todayTokens")}
                value={formatTokens(overview.today_tokens)}
                sub={`${overview.total_calls} ${t("usage.calls")}`}
              />
              <StatCard
                icon={<Database size={16} />}
                label={t("usage.cacheHitRate")}
                value={`${(overview.cache_hit_rate * 100).toFixed(1)}%`}
                sub={`${formatTokens(overview.cached_tokens)} / ${formatTokens(overview.prompt_tokens)}`}
                progress={overview.cache_hit_rate}
              />
              <StatCard
                icon={<Coins size={16} />}
                label={t("usage.sessions")}
                value={String(overview.sessions_count)}
                sub={overview.reasoning_tokens > 0 ? `${formatTokens(overview.reasoning_tokens)} reasoning` : undefined}
              />
            </div>

            {/* Trend Chart (daily or hourly) */}
            {overview.trend.length > 0 && (
              <ChartCard title={overview.hourly ? t("usage.hourlyTrend") : t("usage.dailyTrend")}>
                <MeasuredChartContainer height={260}>{({ width, height }) => <ComposedChart width={width} height={height} data={overview.trend} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                    <XAxis
                      dataKey={overview.hourly ? "hour" : "date"}
                      tick={{ fontSize: 10, fill: "var(--text-tertiary)" }}
                    />
                    <YAxis tick={{ fontSize: 10, fill: "var(--text-tertiary)" }} tickFormatter={formatTokens} />
                    <Tooltip
                      contentStyle={{
                        background: "var(--bg-secondary)",
                        border: "1px solid var(--border)",
                        borderRadius: "8px",
                        fontSize: "12px",
                      }}
                      formatter={(value: unknown, name: unknown) => [formatTokens(Number(value)), String(name)]}
                    />
                    <Legend wrapperStyle={{ fontSize: "11px" }} />
                    {/* Input bar: stacked cached + non-cached */}
                    <Bar
                      dataKey="cached_tokens"
                      name={t("usage.cached")}
                      stackId="input"
                      fill="#10b981"
                      fillOpacity={0.7}
                      radius={[0, 0, 0, 0]}
                    />
                    <Bar
                      dataKey="non_cached_tokens"
                      name={t("usage.nonCached")}
                      stackId="input"
                      fill="var(--brand)"
                      fillOpacity={0.7}
                      radius={[4, 4, 0, 0]}
                    />
                    {/* Output bar: separate */}
                    <Bar
                      dataKey="completion_tokens"
                      name={t("usage.completion")}
                      fill="#f59e0b"
                      fillOpacity={0.7}
                      radius={[4, 4, 0, 0]}
                    />
                    {/* Trend lines for totals */}
                    <Line
                      type="monotone"
                      dataKey="prompt_tokens"
                      name={t("usage.totalInput")}
                      stroke="#10b981"
                      strokeWidth={2}
                      dot={false}
                      legendType="plainline"
                    />
                    <Line
                      type="monotone"
                      dataKey="completion_tokens"
                      name={t("usage.totalOutput")}
                      stroke="#f59e0b"
                      strokeWidth={2}
                      dot={false}
                      legendType="plainline"
                    />
                  </ComposedChart>}</MeasuredChartContainer>
              </ChartCard>
            )}

            {/* By Agent + By Model — with chart type toggle */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {overview.by_agent.length > 0 && (
                <DistributionCard
                  title={t("usage.byAgent")}
                  data={overview.by_agent}
                  nameKey="agent_name"
                />
              )}
              {overview.by_model.length > 0 && (
                <DistributionCard
                  title={t("usage.byModel")}
                  data={overview.by_model}
                  nameKey="model"
                />
              )}
            </div>

            {/* Session Table */}
            <ChartCard title={`${t("usage.sessionDetail")} (${sessionsTotal})`}>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-[var(--text-tertiary)] border-b border-[var(--border)]">
                      <th className="text-left py-2 px-2 font-medium" />
                      <th className="text-left py-2 px-2 font-medium">{t("usage.sessionTitle")}</th>
                      <th className="text-right py-2 px-2 font-medium">{t("usage.prompt")}</th>
                      <th className="text-right py-2 px-2 font-medium">{t("usage.cacheRate")}</th>
                      <th className="text-right py-2 px-2 font-medium">{t("usage.completion")}</th>
                      <th className="text-right py-2 px-2 font-medium">{t("usage.total")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sessions.map((s) => (
                      <SessionRow
                        key={s.session_id}
                        session={s}
                        expanded={expandedSession === s.session_id}
                        detail={expandedSession === s.session_id ? sessionDetail : null}
                        detailLoading={expandedSession === s.session_id && detailLoading}
                        onToggle={() => handleExpand(s.session_id)}
                        t={t}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </ChartCard>
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatCard({
  icon,
  label,
  value,
  sub,
  progress,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  progress?: number;
}) {
  return (
    <div className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-4 space-y-1">
      <div className="flex items-center gap-1.5 text-[var(--text-tertiary)] text-xs font-medium">
        {icon}
        {label}
      </div>
      <div className="text-2xl font-bold text-[var(--text-primary)]">{value}</div>
      {sub && <div className="text-xs text-[var(--text-tertiary)]">{sub}</div>}
      {progress !== undefined && (
        <div className="mt-1 h-1.5 rounded-full bg-[var(--bg-tertiary)] overflow-hidden">
          <div
            className="h-full rounded-full bg-[var(--brand)] transition-all"
            style={{ width: `${progress * 100}%` }}
          />
        </div>
      )}
    </div>
  );
}

function ChartCard({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">{title}</h3>
        {action}
      </div>
      {children}
    </div>
  );
}

/** Distribution card with bar/pie toggle */
function DistributionCard({
  title,
  data,
  nameKey,
}: {
  title: string;
  data: Record<string, unknown>[];
  nameKey: string;
}) {
  const [chartType, setChartType] = useState<"bar" | "pie">("bar");
  const toggleBtn = (
    <button
      onClick={() => setChartType((prev) => (prev === "bar" ? "pie" : "bar"))}
      className="flex items-center gap-1 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-primary)] px-2 py-0.5 rounded-md hover:bg-[var(--bg-tertiary)] transition-colors"
      title={chartType === "bar" ? "Switch to pie" : "Switch to bar"}
    >
      {chartType === "bar" ? <PieIcon size={13} /> : <BarChart3 size={13} />}
      <span className="hidden sm:inline">{chartType === "bar" ? "Pie" : "Bar"}</span>
    </button>
  );

  return (
    <ChartCard title={title} action={toggleBtn}>
      {chartType === "bar" ? (
        <MeasuredChartContainer height={200}>{({ width, height }) => <BarChart width={width} height={height} data={data} layout="vertical" margin={{ left: 10 }}>
            <XAxis type="number" tick={{ fontSize: 10, fill: "var(--text-tertiary)" }} tickFormatter={formatTokens} />
            <YAxis type="category" dataKey={nameKey} tick={{ fontSize: 11, fill: "var(--text-secondary)" }} width={80} />
            <Tooltip
              contentStyle={{
                background: "var(--bg-secondary)",
                border: "1px solid var(--border)",
                borderRadius: "8px",
                fontSize: "12px",
              }}
              formatter={(value: unknown) => formatTokens(Number(value))}
            />
            <Bar dataKey="total_tokens" fill="var(--brand)" radius={[0, 4, 4, 0]}>
              {data.map((_, idx) => (
                <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
              ))}
            </Bar>
          </BarChart>}</MeasuredChartContainer>
      ) : (
        <MeasuredChartContainer height={200}>{({ width, height }) => <PieChart width={width} height={height}>
            <Pie
              data={data}
              dataKey="total_tokens"
              nameKey={nameKey}
              cx="50%"
              cy="50%"
              outerRadius={75}
              innerRadius={40}
              label={(entry: unknown) => (entry as Record<string, unknown>)?.[nameKey] as string || ""}
              labelLine={false}
            >
              {data.map((_, idx) => (
                <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                background: "var(--bg-secondary)",
                border: "1px solid var(--border)",
                borderRadius: "8px",
                fontSize: "12px",
              }}
              formatter={(value: unknown) => formatTokens(Number(value))}
            />
          </PieChart>}</MeasuredChartContainer>
      )}
    </ChartCard>
  );
}

function SessionRow({
  session,
  expanded,
  detail,
  detailLoading,
  onToggle,
  t,
}: {
  session: SessionUsage;
  expanded: boolean;
  detail: SessionUsageDetail | null;
  detailLoading: boolean;
  onToggle: () => void;
  t: (k: string) => string;
}) {
  return (
    <>
      <tr
        onClick={onToggle}
        className="border-b border-[var(--border)] cursor-pointer hover:bg-[var(--bg-tertiary)]/40 transition-colors"
      >
        <td className="py-2 px-2 text-[var(--text-tertiary)]">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </td>
        <td className="py-2 px-2 text-[var(--text-primary)] max-w-xs truncate">
          {session.title || session.session_id.slice(0, 12)}
        </td>
        <td className="text-right py-2 px-2 text-[var(--text-secondary)]">
          {formatTokens(session.prompt_tokens)}
          <span className="text-[var(--text-tertiary)] text-xs ml-1">
            ({formatTokens(session.cached_tokens)})
          </span>
        </td>
        <td className="text-right py-2 px-2 text-[var(--text-secondary)]">
          <CacheBadge rate={session.cache_hit_rate} />
        </td>
        <td className="text-right py-2 px-2 text-[var(--text-secondary)]">
          {formatTokens(session.completion_tokens)}
        </td>
        <td className="text-right py-2 px-2 font-medium text-[var(--text-primary)]">
          {formatTokens(session.total_tokens)}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={6} className="py-3 px-6 bg-[var(--bg-tertiary)]/30">
            {detailLoading ? (
              <div className="text-center py-4 text-[var(--text-tertiary)] text-sm">{t("common.loading")}</div>
            ) : detail ? (
              <div className="space-y-3">
                {/* Per-iteration table */}
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-[var(--text-tertiary)]">
                      <th className="text-left py-1 px-2">#</th>
                      <th className="text-left py-1 px-2">Iter</th>
                      <th className="text-left py-1 px-2">Agent</th>
                      <th className="text-left py-1 px-2">Model</th>
                      <th className="text-right py-1 px-2">{t("usage.prompt")}</th>
                      <th className="text-right py-1 px-2">{t("usage.cached")}</th>
                      <th className="text-right py-1 px-2">{t("usage.nonCached")}</th>
                      <th className="text-right py-1 px-2">{t("usage.completion")}</th>
                      <th className="text-right py-1 px-2">{t("usage.cacheRate")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.records.map((r, idx) => (
                      <tr key={r.id} className="text-[var(--text-secondary)] border-t border-[var(--border)]">
                        <td className="py-1 px-2">{idx + 1}</td>
                        <td className="py-1 px-2 text-[var(--text-tertiary)]">{r.iteration}</td>
                        <td className="py-1 px-2">{r.agent_name}</td>
                        <td className="py-1 px-2 text-[var(--text-tertiary)]">{r.model}</td>
                        <td className="text-right py-1 px-2">{formatTokens(r.prompt_tokens)}</td>
                        <td className="text-right py-1 px-2 text-[#10b981]">{formatTokens(r.cached_tokens)}</td>
                        <td className="text-right py-1 px-2">{formatTokens(r.non_cached_tokens)}</td>
                        <td className="text-right py-1 px-2">{formatTokens(r.completion_tokens)}</td>
                        <td className="text-right py-1 px-2">
                          <CacheBadge rate={r.prompt_tokens > 0 ? r.cached_tokens / r.prompt_tokens : 0} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-center py-4 text-[var(--text-tertiary)] text-sm">{t("usage.noData")}</div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

function CacheBadge({ rate }: { rate: number }) {
  const pct = (rate * 100).toFixed(0);
  const color = rate >= 0.7 ? "#10b981" : rate >= 0.4 ? "#f59e0b" : "#ef4444";
  return (
    <span
      className="inline-block px-1.5 py-0.5 rounded text-xs font-medium"
      style={{ color, background: `${color}15` }}
    >
      {pct}%
    </span>
  );
}

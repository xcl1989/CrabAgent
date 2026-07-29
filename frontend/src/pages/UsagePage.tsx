import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Area, AreaChart, Bar, BarChart, Cell, Tooltip, XAxis, YAxis } from "recharts";
import {
  ArrowDownUp,
  ChevronDown,
  ChevronRight,
  Coins,
  Database,
  RefreshCw,
  Search,
  Sparkles,
  TrendingUp,
  Zap,
} from "lucide-react";
import { MeasuredChartContainer } from "../components/charts/MeasuredChartContainer";
import { cn } from "../lib/cn";
import {
  getOverview,
  getSessionUsageDetail,
  getSessionsUsage,
  getWorkspacesUsage,
  type SessionUsage,
  type SessionUsageDetail,
  type TokenUsageOverview,
  type WorkspaceUsage,
} from "../api/tokenUsage";

const DISTRIBUTION_COLORS = ["var(--brand)", "var(--accent)", "var(--warning)", "var(--accent-2)", "var(--success)"];
const PAGE_SIZE = 15;
type TrendMode = "total" | "input-output" | "cache";
type SessionSort = "total" | "recent" | "cache" | "calls";

function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return String(value);
}

function formatDate(value: string): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export default function UsagePage() {
  const { t } = useTranslation();
  const [days, setDays] = useState(30);
  const [workspace, setWorkspace] = useState("");
  const [overview, setOverview] = useState<TokenUsageOverview | null>(null);
  const [sessions, setSessions] = useState<SessionUsage[]>([]);
  const [sessionsTotal, setSessionsTotal] = useState(0);
  const [workspaces, setWorkspaces] = useState<WorkspaceUsage[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SessionSort>("total");
  const [trendMode, setTrendMode] = useState<TrendMode>("total");
  const [expandedSession, setExpandedSession] = useState<string | null>(null);
  const [sessionDetail, setSessionDetail] = useState<SessionUsageDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setExpandedSession(null);
    setSessionDetail(null);
    try {
      const [ov, sess] = await Promise.all([
        getOverview(days, workspace),
        getSessionsUsage(PAGE_SIZE, 0, days, workspace),
      ]);
      setOverview(ov);
      setSessions(sess.sessions);
      setSessionsTotal(sess.total);
    } finally {
      setLoading(false);
    }
  }, [days, workspace]);

  useEffect(() => { void fetchData(); }, [fetchData]);
  useEffect(() => { getWorkspacesUsage().then(setWorkspaces).catch(() => {}); }, []);

  const loadMore = async () => {
    setLoadingMore(true);
    try {
      const result = await getSessionsUsage(PAGE_SIZE, sessions.length, days, workspace);
      setSessions((current) => [...current, ...result.sessions]);
    } finally {
      setLoadingMore(false);
    }
  };

  const handleExpand = async (sessionId: string) => {
    if (expandedSession === sessionId) {
      setExpandedSession(null);
      setSessionDetail(null);
      return;
    }
    setExpandedSession(sessionId);
    setDetailLoading(true);
    try {
      setSessionDetail(await getSessionUsageDetail(sessionId));
    } catch {
      setSessionDetail(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const visibleSessions = useMemo(() => {
    const query = search.trim().toLowerCase();
    return sessions
      .filter((session) => !query || `${session.title} ${session.session_id}`.toLowerCase().includes(query))
      .sort((a, b) => {
        if (sort === "recent") return new Date(b.last_active).getTime() - new Date(a.last_active).getTime();
        if (sort === "cache") return b.cache_hit_rate - a.cache_hit_rate;
        if (sort === "calls") return b.calls - a.calls;
        return b.total_tokens - a.total_tokens;
      });
  }, [search, sessions, sort]);

  const rangeOptions = [
    { days: 1, label: t("usage.rangeToday") }, { days: 7, label: t("usage.range7d") },
    { days: 30, label: t("usage.range30d") }, { days: 365, label: t("usage.rangeAll") },
  ];
  const wsLabel = (value: string) => value.split("/").filter(Boolean).pop() || value;
  const largestSessionShare = overview && sessions[0] ? sessions[0].total_tokens / overview.total_tokens : 0;
  const cacheStatus = overview && overview.cache_hit_rate >= 0.7 ? t("usage.cacheHealthy") : t("usage.cacheOpportunity");

  return (
    <div className="h-full overflow-y-auto">
      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-5">
        <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-[var(--brand)] mb-1"><Coins size={19} /><span className="text-xs font-bold tracking-[0.16em] uppercase">{t("usage.insights")}</span></div>
            <h1 className="text-2xl font-semibold tracking-tight">{t("usage.title")}</h1>
            <p className="text-sm text-[var(--text-secondary)] mt-1">{t("usage.description")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select value={workspace} onChange={(event) => setWorkspace(event.target.value)} className="min-w-36 text-xs font-medium px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] text-[var(--text-secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]">
              <option value="">{t("usage.allProjects")}</option>
              {workspaces.map((item) => <option key={item.workspace} value={item.workspace}>{wsLabel(item.workspace)} ({formatTokens(item.total_tokens)})</option>)}
            </select>
            <button onClick={() => void fetchData()} disabled={loading} title={t("usage.refresh")} className="p-2 rounded-lg border border-[var(--border)] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] disabled:opacity-50"><RefreshCw size={15} className={loading ? "animate-spin" : ""} /></button>
          </div>
        </header>

        <div className="flex w-full sm:w-fit gap-1 p-1 rounded-xl bg-[var(--bg-tertiary)]">
          {rangeOptions.map((option) => <button key={option.days} onClick={() => setDays(option.days)} className={cn("flex-1 sm:flex-none px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-colors", days === option.days ? "bg-[var(--bg-secondary)] text-[var(--text-primary)] shadow-sm" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]")}>{option.label}</button>)}
        </div>

        {loading ? <PageState label={t("common.loading")} /> : !overview || overview.total_calls === 0 ? <PageState label={t("usage.noData")} /> : <>
          <section className="grid grid-cols-2 xl:grid-cols-4 gap-3">
            <MetricCard icon={<Coins size={16} />} label={t("usage.periodUsage")} value={formatTokens(overview.total_tokens)} detail={`${formatTokens(overview.prompt_tokens)} ${t("usage.inputAndOutput")} ${formatTokens(overview.completion_tokens)}`} emphasis />
            <MetricCard icon={<Zap size={16} />} label={t("usage.calls")} value={String(overview.total_calls)} detail={`${formatTokens(Math.round(overview.total_tokens / overview.total_calls))} ${t("usage.perCall")}`} />
            <MetricCard icon={<Database size={16} />} label={t("usage.cacheHitRate")} value={`${(overview.cache_hit_rate * 100).toFixed(0)}%`} detail={`${cacheStatus} - ${formatTokens(overview.cached_tokens)} ${t("usage.cached")}`} progress={overview.cache_hit_rate} />
            <MetricCard icon={<TrendingUp size={16} />} label={t("usage.activeSessions")} value={String(overview.sessions_count)} detail={largestSessionShare > 0 ? `${t("usage.topSession")} ${(largestSessionShare * 100).toFixed(0)}%` : undefined} />
          </section>

          {overview.trend.length > 0 && <Card title={overview.hourly ? t("usage.hourlyTrend") : t("usage.dailyTrend")} action={<TrendTabs mode={trendMode} onChange={setTrendMode} t={t} />}>
            <MeasuredChartContainer height={260}>{({ width, height }) => <AreaChart width={width} height={height} data={overview.trend} margin={{ top: 12, right: 8, left: -12, bottom: 0 }}>
              <defs><linearGradient id="usage-total" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--brand)" stopOpacity={0.42} /><stop offset="100%" stopColor="var(--brand)" stopOpacity={0.02} /></linearGradient></defs>
              <XAxis dataKey={overview.hourly ? "hour" : "date"} tick={{ fontSize: 10, fill: "var(--text-tertiary)" }} tickLine={false} axisLine={false} minTickGap={28} />
              <YAxis tick={{ fontSize: 10, fill: "var(--text-tertiary)" }} tickFormatter={formatTokens} tickLine={false} axisLine={false} width={48} />
              <Tooltip contentStyle={tooltipStyle} formatter={(value: unknown, name: unknown) => [formatTokens(Number(value)), String(name)]} />
              {trendMode === "total" && <Area type="monotone" dataKey="total_tokens" name={t("usage.total")} stroke="var(--brand)" strokeWidth={2.5} fill="url(#usage-total)" />}
              {trendMode === "input-output" && <><Area type="monotone" dataKey="prompt_tokens" name={t("usage.prompt")} stackId="flow" stroke="var(--accent)" fill="var(--accent)" fillOpacity={0.25} /><Area type="monotone" dataKey="completion_tokens" name={t("usage.completion")} stackId="flow" stroke="var(--warning)" fill="var(--warning)" fillOpacity={0.3} /></>}
              {trendMode === "cache" && <><Area type="monotone" dataKey="cached_tokens" name={t("usage.cached")} stackId="cache" stroke="var(--success)" fill="var(--success)" fillOpacity={0.3} /><Area type="monotone" dataKey="non_cached_tokens" name={t("usage.nonCached")} stackId="cache" stroke="var(--warning)" fill="var(--warning)" fillOpacity={0.3} /></>}
            </AreaChart>}</MeasuredChartContainer>
          </Card>}

          <section className="grid lg:grid-cols-2 gap-4">
            <RankedDistribution title={t("usage.byModel")} data={overview.by_model} nameKey="model" total={overview.total_tokens} callsLabel={t("usage.calls")} />
            <RankedDistribution title={t("usage.byAgent")} data={overview.by_agent} nameKey="agent_name" total={overview.total_tokens} callsLabel={t("usage.calls")} />
          </section>

          <Card title={`${t("usage.sessionDetail")} (${sessionsTotal})`} action={<span className="hidden sm:flex items-center gap-1.5 text-xs text-[var(--text-tertiary)]"><Sparkles size={13} /> {t("usage.sessionHint")}</span>}>
            <div className="flex flex-col sm:flex-row gap-2 mb-4">
              <label className="relative flex-1"><Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("usage.searchSessions")} className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--brand)]" /></label>
              <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)]"><ArrowDownUp size={14} /><select value={sort} onChange={(event) => setSort(event.target.value as SessionSort)} className="px-2.5 py-2 rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] text-[var(--text-primary)]"><option value="total">{t("usage.sortUsage")}</option><option value="recent">{t("usage.sortRecent")}</option><option value="cache">{t("usage.sortCache")}</option><option value="calls">{t("usage.sortCalls")}</option></select></label>
            </div>
            <div className="overflow-x-auto"><table className="w-full min-w-[650px] text-sm"><thead><tr className="border-b border-[var(--border)] text-[var(--text-tertiary)] text-xs"><th className="w-8" /><th className="text-left font-medium py-2 px-2">{t("usage.sessionTitle")}</th><th className="text-right font-medium py-2 px-2">{t("usage.total")}</th><th className="text-right font-medium py-2 px-2">{t("usage.share")}</th><th className="text-right font-medium py-2 px-2">{t("usage.cacheRate")}</th><th className="text-right font-medium py-2 px-2">{t("usage.calls")}</th><th className="text-right font-medium py-2 px-2">{t("usage.lastActive")}</th></tr></thead>
              <tbody>{visibleSessions.map((session) => <SessionRow key={session.session_id} session={session} overviewTotal={overview.total_tokens} expanded={expandedSession === session.session_id} detail={expandedSession === session.session_id ? sessionDetail : null} detailLoading={expandedSession === session.session_id && detailLoading} onToggle={() => void handleExpand(session.session_id)} t={t} />)}</tbody>
            </table></div>
            {visibleSessions.length === 0 && <p className="py-8 text-center text-sm text-[var(--text-tertiary)]">{t("usage.noMatches")}</p>}
            {sessions.length < sessionsTotal && <button onClick={() => void loadMore()} disabled={loadingMore} className="mt-4 w-full py-2 text-sm font-semibold rounded-lg border border-[var(--border)] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] disabled:opacity-50">{loadingMore ? t("common.loading") : t("usage.loadMore")}</button>}
          </Card>
        </>}
      </main>
    </div>
  );
}

const tooltipStyle = { background: "var(--bg-elevated)", border: "1px solid var(--border-strong)", borderRadius: "10px", fontSize: "12px", color: "var(--text-primary)" };

function PageState({ label }: { label: string }) { return <div className="py-24 text-center text-sm text-[var(--text-tertiary)]">{label}</div>; }
function Card({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) { return <section className="rounded-2xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4 sm:p-5 shadow-[var(--shadow-sm)]"><div className="flex items-center justify-between gap-3 mb-4"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>{children}</section>; }
function MetricCard({ icon, label, value, detail, progress, emphasis = false }: { icon: React.ReactNode; label: string; value: string; detail?: string; progress?: number; emphasis?: boolean }) { return <div className={cn("rounded-2xl border p-4 min-h-32", emphasis ? "border-[var(--brand-border)] bg-[var(--brand-bg)]" : "border-[var(--border)] bg-[var(--bg-secondary)]")}><div className="flex items-center gap-1.5 text-xs font-semibold text-[var(--text-secondary)]">{icon}{label}</div><p className="mt-3 text-2xl font-semibold tracking-tight">{value}</p>{detail && <p className="mt-1 text-xs text-[var(--text-tertiary)] truncate">{detail}</p>}{progress !== undefined && <div className="mt-3 h-1.5 rounded-full bg-[var(--bg-tertiary)] overflow-hidden"><div className="h-full rounded-full bg-[var(--success)]" style={{ width: `${progress * 100}%` }} /></div>}</div>; }
function TrendTabs({ mode, onChange, t }: { mode: TrendMode; onChange: (mode: TrendMode) => void; t: (key: string) => string }) { return <div className="flex gap-1 p-0.5 bg-[var(--bg-tertiary)] rounded-lg">{(["total", "input-output", "cache"] as TrendMode[]).map((item) => <button key={item} onClick={() => onChange(item)} className={cn("px-2 py-1 rounded-md text-[11px] font-medium", mode === item ? "bg-[var(--bg-secondary)] text-[var(--text-primary)]" : "text-[var(--text-tertiary)]")}>{t(`usage.trend${item === "total" ? "Total" : item === "cache" ? "Cache" : "Flow"}`)}</button>)}</div>; }
function RankedDistribution({ title, data, nameKey, total, callsLabel }: { title: string; data: Record<string, unknown>[]; nameKey: string; total: number; callsLabel: string }) { return <Card title={title}>{data.slice(0, 5).map((item, index) => { const value = Number(item.total_tokens); const share = total ? value / total : 0; return <div key={String(item[nameKey])} className="py-2.5 border-b last:border-0 border-[var(--border-subtle)]"><div className="flex justify-between gap-3 text-xs mb-1.5"><span className="text-[var(--text-primary)] font-medium truncate">{String(item[nameKey] || "Unknown")}</span><span className="text-[var(--text-secondary)] shrink-0">{formatTokens(value)} <span className="text-[var(--text-tertiary)]">{(share * 100).toFixed(0)}%</span></span></div><div className="h-1.5 rounded-full bg-[var(--bg-tertiary)] overflow-hidden"><div className="h-full rounded-full" style={{ width: `${share * 100}%`, background: DISTRIBUTION_COLORS[index] }} /></div><p className="mt-1 text-[11px] text-[var(--text-tertiary)]">{Number(item.calls)} {callsLabel}</p></div>; })}</Card>; }
function SessionRow({ session, overviewTotal, expanded, detail, detailLoading, onToggle, t }: { session: SessionUsage; overviewTotal: number; expanded: boolean; detail: SessionUsageDetail | null; detailLoading: boolean; onToggle: () => void; t: (key: string) => string }) { const share = overviewTotal ? session.total_tokens / overviewTotal : 0; return <><tr onClick={onToggle} className="cursor-pointer border-b border-[var(--border-subtle)] hover:bg-[var(--bg-tertiary)]/50"><td className="px-2 text-[var(--text-tertiary)]">{expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</td><td className="py-3 px-2 max-w-64"><p className="font-medium truncate">{session.title || session.session_id.slice(0, 12)}</p><p className="text-[11px] text-[var(--text-tertiary)]">{formatTokens(session.prompt_tokens)} {t("usage.inputAndOutput")} {formatTokens(session.completion_tokens)}</p></td><td className="py-3 px-2 text-right font-semibold">{formatTokens(session.total_tokens)}</td><td className="py-3 px-2 text-right text-[var(--text-secondary)]">{(share * 100).toFixed(0)}%</td><td className="py-3 px-2 text-right"><CacheBadge rate={session.cache_hit_rate} /></td><td className="py-3 px-2 text-right text-[var(--text-secondary)]">{session.calls}</td><td className="py-3 px-2 text-right text-xs text-[var(--text-tertiary)]">{formatDate(session.last_active)}</td></tr>{expanded && <tr><td colSpan={7} className="px-5 py-4 bg-[var(--bg-tertiary)]/35">{detailLoading ? <p className="text-center text-sm text-[var(--text-tertiary)]">{t("common.loading")}</p> : detail ? <div className="grid sm:grid-cols-3 gap-3"><DetailMetric label={t("usage.total")} value={formatTokens(detail.total.total_tokens)} /><DetailMetric label={t("usage.calls")} value={String(detail.total.calls)} /><DetailMetric label={t("usage.cacheHitRate")} value={`${(detail.total.cache_hit_rate * 100).toFixed(0)}%`} /><div className="sm:col-span-3 text-xs text-[var(--text-secondary)]">{t("usage.records")}: {detail.records.slice(0, 5).map((record) => `${record.model} ${formatTokens(record.total_tokens)}`).join(" · ")}{detail.records.length > 5 ? " ..." : ""}</div></div> : <p className="text-center text-sm text-[var(--text-tertiary)]">{t("usage.noData")}</p>}</td></tr>}</>; }
function DetailMetric({ label, value }: { label: string; value: string }) { return <div className="rounded-lg bg-[var(--bg-secondary)] border border-[var(--border)] px-3 py-2"><p className="text-[11px] text-[var(--text-tertiary)]">{label}</p><p className="font-semibold">{value}</p></div>; }
function CacheBadge({ rate }: { rate: number }) { const color = rate >= 0.7 ? "var(--success)" : rate >= 0.4 ? "var(--warning)" : "var(--danger)"; return <span className="inline-block px-1.5 py-0.5 rounded text-xs font-semibold" style={{ color, background: `color-mix(in srgb, ${color} 14%, transparent)` }}>{(rate * 100).toFixed(0)}%</span>; }

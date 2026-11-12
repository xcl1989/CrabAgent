import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Area, AreaChart, Tooltip, XAxis, YAxis } from "recharts";
import { CalendarDays, RefreshCw } from "lucide-react";

import { getOverview } from "../api/tokenUsage";
import { MeasuredChartContainer } from "./charts/MeasuredChartContainer";
import { cn } from "../lib/cn";

/**
 * UsageHeatmap — GitHub-style yearly contribution heatmap for token usage.
 *
 * Three views (tabs):
 *  - daily:      calendar grid, columns = weeks, rows = weekdays, color intensity = tokens
 *  - weekly:     one row of ~53 cells, each a full week aggregate
 *  - cumulative: area chart of running token total over the year
 *
 * Data comes from the existing /token-usage/overview?days=365 endpoint (daily
 * trend, date format YYYY-MM-DD) — no backend change required.
 */

type ViewMode = "daily" | "weekly" | "cumulative";

interface DayEntry {
  date: string; // YYYY-MM-DD
  tokens: number;
}

const CELL = 11; // cell size in px
const GAP = 3; // gap between cells in px

function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return String(value);
}

function toDateKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

interface GridCell {
  date: string;
  tokens: number; // -1 → placeholder (outside range)
  month: number;
  weekIndex: number;
  dayIndex: number;
}

export default function UsageHeatmap({ workspace }: { workspace: string }) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<ViewMode>("daily");
  const [trend, setTrend] = useState<DayEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [hover, setHover] = useState<{ label: string; x: number; y: number } | null>(null);

  const fetchTrend = useCallback(async () => {
    setLoading(true);
    try {
      const overview = await getOverview(365, workspace);
      setTrend(
        overview.trend
          .filter((p) => p.date)
          .map((p) => ({ date: p.date as string, tokens: p.total_tokens })),
      );
    } catch {
      setTrend([]);
    } finally {
      setLoading(false);
    }
  }, [workspace]);

  useEffect(() => {
    void fetchTrend();
  }, [fetchTrend]);

  const tokensByDate = useMemo(() => {
    const map = new Map<string, number>();
    for (const item of trend) map.set(item.date, item.tokens);
    return map;
  }, [trend]);

  // ── Calendar grid: columns = weeks (first row = Sunday), ends today ──
  const grid = useMemo<GridCell[][]>(() => {
    const now = new Date();
    const end = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const start = new Date(end);
    start.setDate(start.getDate() - 364);
    start.setDate(start.getDate() - start.getDay()); // align first column to Sunday

    const weeks: GridCell[][] = [];
    const cursor = new Date(start);
    let weekIndex = 0;
    while (cursor <= end) {
      const week: GridCell[] = [];
      for (let dayIndex = 0; dayIndex < 7; dayIndex++) {
        const inRange = cursor <= end;
        const key = inRange ? toDateKey(cursor) : "";
        week.push({
          date: key,
          tokens: inRange ? (tokensByDate.get(key) ?? 0) : -1,
          month: cursor.getMonth(),
          weekIndex,
          dayIndex,
        });
        cursor.setDate(cursor.getDate() + 1);
      }
      weeks.push(week);
      weekIndex++;
    }
    return weeks;
  }, [tokensByDate]);

  const maxTokens = useMemo(() => {
    let max = 0;
    for (const week of grid) for (const cell of week) max = Math.max(max, cell.tokens);
    return max;
  }, [grid]);

  // Intensity level 0 (empty) … 4 (max)
  const levelOf = (tokens: number): number => {
    if (tokens <= 0) return 0;
    return Math.min(4, 1 + Math.floor((tokens / maxTokens) * 4));
  };

  const cellStyle = (tokens: number): React.CSSProperties => {
    const level = levelOf(tokens);
    if (level === 0) return { background: "var(--bg-tertiary)" };
    return { background: "var(--brand)", opacity: [0, 0.28, 0.48, 0.7, 1][level] };
  };

  const monthLabel = useMemo(
    () => new Intl.DateTimeFormat(undefined, { month: "short" }),
    [],
  );
  const dayLabel = useMemo(
    () => new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }),
    [],
  );

  // Month labels under the grid: show when the column's month changes
  const monthMarks = useMemo(() => {
    const marks: { weekIndex: number; label: string }[] = [];
    let last = -1;
    for (const week of grid) {
      const m = week[0].month;
      if (m !== last) {
        marks.push({ weekIndex: week[0].weekIndex, label: monthLabel.format(new Date(2020, m, 1)) });
        last = m;
      }
    }
    return marks;
  }, [grid, monthLabel]);

  // Weekly aggregates (one value per grid column)
  const weekly = useMemo(
    () =>
      grid.map((week) => {
        const valid = week.filter((c) => c.tokens >= 0 && c.date);
        const first = valid[0];
        const last = valid[valid.length - 1];
        return {
          startDate: first?.date ?? "", // real YYYY-MM-DD for month marks
          tokens: week.reduce((sum, c) => sum + Math.max(0, c.tokens), 0),
          label:
            first && last
              ? `${dayLabel.format(new Date(first.date))} - ${dayLabel.format(new Date(last.date))}`
              : "",
        };
      }),
    [grid, dayLabel],
  );

  // Cumulative series for the area chart
  const cumulative = useMemo(() => {
    const sorted = [...trend].sort((a, b) => a.date.localeCompare(b.date));
    let acc = 0;
    return sorted.map((item) => {
      acc += item.tokens;
      return { date: item.date.slice(5), tokens: acc };
    });
  }, [trend]);

  const tabs: { key: ViewMode; label: string }[] = [
    { key: "daily", label: t("usage.heatmapDaily") },
    { key: "weekly", label: t("usage.heatmapWeekly") },
    { key: "cumulative", label: t("usage.heatmapCumulative") },
  ];

  return (
    <section className="rounded-2xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4 sm:p-5 shadow-[var(--shadow-sm)]">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <CalendarDays size={15} className="text-[var(--brand)]" />
          {t("usage.heatmapTitle")}
        </h2>
        <div className="flex items-center gap-2">
          <div className="flex gap-1 p-0.5 bg-[var(--bg-tertiary)] rounded-lg">
            {tabs.map((item) => (
              <button
                key={item.key}
                onClick={() => setMode(item.key)}
                className={cn(
                  "px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors",
                  mode === item.key
                    ? "bg-[var(--bg-secondary)] text-[var(--text-primary)]"
                    : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]",
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
          <button
            onClick={() => void fetchTrend()}
            disabled={loading}
            title={t("usage.refresh")}
            className="p-1.5 rounded-lg border border-[var(--border)] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] disabled:opacity-50"
          >
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {loading ? (
        <div className="py-16 text-center text-sm text-[var(--text-tertiary)]">{t("common.loading")}</div>
      ) : trend.length === 0 ? (
        <div className="py-16 text-center text-sm text-[var(--text-tertiary)]">{t("usage.noData")}</div>
      ) : mode === "cumulative" ? (
        <MeasuredChartContainer height={220}>
          {({ width, height }) => (
            <AreaChart width={width} height={height} data={cumulative} margin={{ top: 12, right: 8, left: 8, bottom: 0 }}>
              <defs>
                <linearGradient id="heatmap-cumulative" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--brand)" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="var(--brand)" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: "var(--text-tertiary)" }} tickLine={false} axisLine={false} minTickGap={48} />
              <YAxis tick={{ fontSize: 10, fill: "var(--text-tertiary)" }} tickFormatter={formatTokens} tickLine={false} axisLine={false} width={56} />
              <Tooltip
                contentStyle={{
                  background: "var(--bg-elevated)",
                  border: "1px solid var(--border-strong)",
                  borderRadius: "10px",
                  fontSize: "12px",
                  color: "var(--text-primary)",
                }}
                formatter={(value: unknown) => [formatTokens(Number(value)), t("usage.total")]}
              />
              <Area type="monotone" dataKey="tokens" stroke="var(--brand)" strokeWidth={2.5} fill="url(#heatmap-cumulative)" />
            </AreaChart>
          )}
        </MeasuredChartContainer>
      ) : (
        <div className="overflow-x-auto pb-1">
          <div className="relative mx-auto" style={{ width: mode === "daily" ? grid.length * (CELL + GAP) : weekly.length * (CELL * 2 + GAP) }}>
            {mode === "daily" ? (
              <div className="relative" style={{ height: 7 * (CELL + GAP) }}>
                {grid.map((week, wi) =>
                  week.map((cell, di) => (
                    <div
                      key={`${wi}-${di}`}
                      className="absolute rounded-[3px] cursor-pointer hover:ring-2 hover:ring-[var(--brand)]/40"
                      style={{
                        ...cellStyle(cell.tokens),
                        left: wi * (CELL + GAP),
                        top: di * (CELL + GAP),
                        width: CELL,
                        height: CELL,
                        visibility: cell.tokens < 0 ? "hidden" : "visible",
                      }}
                      onMouseEnter={(e) =>
                        cell.tokens >= 0 &&
                        setHover({
                          label: `${dayLabel.format(new Date(cell.date))} · ${formatTokens(cell.tokens)} tokens`,
                          x: e.clientX,
                          y: e.clientY,
                        })
                      }
                      onMouseLeave={() => setHover(null)}
                    />
                  )),
                )}
                {hover && (
                  <div
                    className="fixed z-50 pointer-events-none whitespace-nowrap px-2 py-1 rounded-md text-[11px] bg-[var(--bg-elevated)] border border-[var(--border-strong)] text-[var(--text-primary)] shadow-md"
                    style={{
                      left: hover.x,
                      top: hover.y < 70 ? hover.y + 22 : hover.y - 36,
                      transform: "translateX(-50%)",
                    }}
                  >
                    {hover.label}
                  </div>
                )}
              </div>
            ) : (
              <div className="relative" style={{ height: CELL * 2 + GAP }}>
                {weekly.map((week, wi) => (
                  <div
                    key={wi}
                    className="absolute rounded-[3px] cursor-pointer hover:ring-2 hover:ring-[var(--brand)]/40"
                    style={{ ...cellStyle(week.tokens), left: wi * (CELL * 2 + GAP), top: 0, width: CELL * 2, height: CELL * 2 }}
                    title={`${week.label} · ${formatTokens(week.tokens)} tokens`}
                  />
                ))}
              </div>
            )}
            {/* Month labels along the bottom (matching the reference layout) */}
            <div className="relative mt-2" style={{ height: 14 }}>
              {(mode === "daily" ? monthMarks : weeklyMonthMarks(weekly, monthLabel)).map((mark) => (
                <span
                  key={mark.weekIndex}
                  className="absolute text-[10px] text-[var(--text-tertiary)]"
                  style={{ left: mark.weekIndex * (CELL + GAP), top: 0 }}
                >
                  {mark.label}
                </span>
              ))}
            </div>
            {/* Legend */}
            <div className="mt-2 flex items-center justify-end gap-1 text-[10px] text-[var(--text-tertiary)]">
              <span>{t("usage.heatmapLess")}</span>
              {[0, 1, 2, 3, 4].map((level) => (
                <span key={level} className="rounded-[3px] inline-block" style={{ ...cellStyle(level === 0 ? 0 : maxTokens * (level / 4)), width: CELL, height: CELL }} />
              ))}
              <span>{t("usage.heatmapMore")}</span>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

/** Month marks for the weekly row (cells are double-width). */
function weeklyMonthMarks(
  weekly: { startDate: string }[],
  monthLabel: Intl.DateTimeFormat,
): { weekIndex: number; label: string }[] {
  const marks: { weekIndex: number; label: string }[] = [];
  let last = "";
  weekly.forEach((week, index) => {
    // startDate is a real YYYY-MM-DD — never parse the formatted label back
    if (!week.startDate) return;
    const month = monthLabel.format(new Date(week.startDate));
    if (month !== last) {
      marks.push({ weekIndex: index, label: month });
      last = month;
    }
  });
  return marks;
}

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  LineChart,
  Line,
  ComposedChart,
  Legend,
} from "recharts";
import { getAgentGrowth, GrowthPoint } from "../api/agents";
import { useThemeColors } from "../lib/theme-colors";
import { MeasuredChartContainer } from "./charts/MeasuredChartContainer";

interface AgentGrowthChartProps {
  agentName: string;
  displayName: string;
}

type ViewMode = "overview" | "elapsed" | "tokens";

export default function AgentGrowthChart({
  agentName,
  displayName,
}: AgentGrowthChartProps) {
  const [data, setData] = useState<GrowthPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState<ViewMode>("overview");
  const { t } = useTranslation();
  const colors = useThemeColors();

  useEffect(() => {
    setLoading(true);
    getAgentGrowth(agentName, 30)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [agentName]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <span className="text-sm text-[var(--text-tertiary)]">{t("agents.loading")}</span>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-48">
        <span className="text-sm text-[var(--text-tertiary)]">
          No growth data for {displayName} yet
        </span>
      </div>
    );
  }

  const tooltipStyle = {
    background: "var(--bg-secondary)",
    border: "1px solid var(--border)",
    borderRadius: 6,
    fontSize: 11,
    fontFamily: "'SF Mono', monospace",
    color: "var(--text-primary)",
  };

  const axisTick = { fontSize: 10, fill: "var(--text-tertiary)" };
  const gridStroke = "var(--border)";

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium text-[var(--text-primary)] font-mono">
          {displayName} — Last 30 Days
        </span>
        <div className="flex gap-1">
          {(["overview", "elapsed", "tokens"] as ViewMode[]).map((m) => (
            <button
              key={m}
              className="text-xs px-2 py-0.5 rounded transition-colors font-mono"
              style={{
                background:
                  mode === m ? "var(--bg-tertiary)" : "transparent",
                color:
                  mode === m
                    ? "var(--text-primary)"
                    : "var(--text-tertiary)",
                border:
                  mode === m
                    ? "1px solid var(--border)"
                    : "1px solid transparent",
              }}
              onClick={() => setMode(m)}
            >
              {m === "overview"
                ? t("agentChart.tasksRate")
                : m === "elapsed"
                  ? t("agentChart.avgTime")
                  : t("agentChart.avgTokens")}
            </button>
          ))}
        </div>
      </div>

      <div style={{ width: "100%", height: 200 }}>
        {mode === "overview" ? (
          <MeasuredChartContainer height={200}>{({ width, height }) => <ComposedChart width={width} height={height}
              data={data}
              margin={{ top: 5, right: 5, bottom: 5, left: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} />
              <XAxis
                dataKey="date"
                tick={axisTick}
                tickFormatter={(v) => v.slice(5)}
              />
              <YAxis yAxisId="left" tick={axisTick} allowDecimals={false} />
              <YAxis
                yAxisId="right"
                orientation="right"
                domain={[0, 100]}
                tick={axisTick}
                tickFormatter={(v) => `${v}%`}
              />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend
                wrapperStyle={{
                  fontSize: 10,
                  color: "var(--text-tertiary)",
                }}
              />
              <Bar
                yAxisId="left"
                dataKey="total"
                name={t("agentChart.tasks")}
                fill={colors.accent}
                radius={[2, 2, 0, 0]}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="success_rate"
                name={t("agentChart.successRate")}
                stroke={colors.success}
                strokeWidth={2}
                dot={{ r: 2, fill: colors.success }}
              />
            </ComposedChart>}</MeasuredChartContainer>
        ) : mode === "elapsed" ? (
          <MeasuredChartContainer height={200}>{({ width, height }) => <LineChart width={width} height={height}
              data={data}
              margin={{ top: 5, right: 5, bottom: 5, left: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} />
              <XAxis
                dataKey="date"
                tick={axisTick}
                tickFormatter={(v) => v.slice(5)}
              />
              <YAxis tick={axisTick} />
              <Tooltip
                contentStyle={tooltipStyle}
                formatter={(value) => [`${value}s`, t("agentChart.avgElapsed")]}
              />
              <Line
                type="monotone"
                dataKey="avg_elapsed"
                name={t("agentChart.avgElapsed")}
                stroke={colors.warning}
                strokeWidth={2}
                dot={{ r: 2, fill: colors.warning }}
              />
            </LineChart>}</MeasuredChartContainer>
        ) : (
          <MeasuredChartContainer height={200}>{({ width, height }) => <LineChart width={width} height={height}
              data={data}
              margin={{ top: 5, right: 5, bottom: 5, left: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} />
              <XAxis
                dataKey="date"
                tick={axisTick}
                tickFormatter={(v) => v.slice(5)}
              />
              <YAxis tick={axisTick} />
              <Tooltip contentStyle={tooltipStyle} />
              <Line
                type="monotone"
                dataKey="avg_tokens"
                name={t("agentChart.avgTokens")}
                stroke={colors.accent2}
                strokeWidth={2}
                dot={{ r: 2, fill: colors.accent2 }}
              />
            </LineChart>}</MeasuredChartContainer>
        )}
      </div>
    </div>
  );
}

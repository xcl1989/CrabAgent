import { useState, useEffect } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, ComposedChart, Legend,
} from "recharts";
import { getAgentGrowth, GrowthPoint } from "../api/agents";

interface AgentGrowthChartProps {
  agentName: string;
  displayName: string;
}

type ViewMode = "overview" | "elapsed" | "tokens";

export default function AgentGrowthChart({ agentName, displayName }: AgentGrowthChartProps) {
  const [data, setData] = useState<GrowthPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState<ViewMode>("overview");

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
        <span className="text-sm" style={{ color: "var(--text-tertiary)" }}>Loading...</span>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-48">
        <span className="text-sm" style={{ color: "var(--text-tertiary)" }}>
          No growth data for {displayName} yet
        </span>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <span
          className="text-xs font-medium"
          style={{ color: "var(--text-primary)", fontFamily: "'SF Mono', monospace" }}
        >
          {displayName} — Last 30 Days
        </span>
        <div className="flex gap-1">
          {(["overview", "elapsed", "tokens"] as ViewMode[]).map((m) => (
            <button
              key={m}
              className="text-xs px-2 py-0.5 rounded transition-colors"
              style={{
                background: mode === m ? "var(--bg-tertiary)" : "transparent",
                color: mode === m ? "var(--text-primary)" : "var(--text-tertiary)",
                border: mode === m ? "1px solid var(--border)" : "1px solid transparent",
                fontFamily: "'SF Mono', monospace",
              }}
              onClick={() => setMode(m)}
            >
              {m === "overview" ? "Tasks+Rate" : m === "elapsed" ? "Avg Time" : "Avg Tokens"}
            </button>
          ))}
        </div>
      </div>

      <div style={{ width: "100%", height: 200 }}>
        {mode === "overview" ? (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10, fill: "var(--text-tertiary)" }}
                tickFormatter={(v) => v.slice(5)}
              />
              <YAxis
                yAxisId="left"
                tick={{ fontSize: 10, fill: "var(--text-tertiary)" }}
                allowDecimals={false}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                domain={[0, 100]}
                tick={{ fontSize: 10, fill: "var(--text-tertiary)" }}
                tickFormatter={(v) => `${v}%`}
              />
              <Tooltip
                contentStyle={{
                  background: "var(--bg-secondary)",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  fontSize: 11,
                  fontFamily: "'SF Mono', monospace",
                  color: "var(--text-primary)",
                }}
              />
              <Legend wrapperStyle={{ fontSize: 10, color: "var(--text-tertiary)" }} />
              <Bar yAxisId="left" dataKey="total" name="Tasks" fill="#60a5fa" radius={[2, 2, 0, 0]} />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="success_rate"
                name="Success Rate"
                stroke="#34d399"
                strokeWidth={2}
                dot={{ r: 2, fill: "#34d399" }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        ) : mode === "elapsed" ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10, fill: "var(--text-tertiary)" }}
                tickFormatter={(v) => v.slice(5)}
              />
              <YAxis tick={{ fontSize: 10, fill: "var(--text-tertiary)" }} />
              <Tooltip
                contentStyle={{
                  background: "var(--bg-secondary)",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  fontSize: 11,
                  fontFamily: "'SF Mono', monospace",
                  color: "var(--text-primary)",
                }}
                formatter={(value) => [`${value}s`, "Avg Elapsed"]}
              />
              <Line
                type="monotone"
                dataKey="avg_elapsed"
                name="Avg Elapsed"
                stroke="#fbbf24"
                strokeWidth={2}
                dot={{ r: 2, fill: "#fbbf24" }}
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10, fill: "var(--text-tertiary)" }}
                tickFormatter={(v) => v.slice(5)}
              />
              <YAxis tick={{ fontSize: 10, fill: "var(--text-tertiary)" }} />
              <Tooltip
                contentStyle={{
                  background: "var(--bg-secondary)",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  fontSize: 11,
                  fontFamily: "'SF Mono', monospace",
                  color: "var(--text-primary)",
                }}
              />
              <Line
                type="monotone"
                dataKey="avg_tokens"
                name="Avg Tokens"
                stroke="#a78bfa"
                strokeWidth={2}
                dot={{ r: 2, fill: "#a78bfa" }}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}

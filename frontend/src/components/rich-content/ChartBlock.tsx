import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from "recharts";
import { AlertTriangle, Loader2, TrendingDown, TrendingUp } from "lucide-react";
import { parseChartSpec, parseKpiSpec } from "./chartSchema";
import { VisualizationFrame } from "./VisualizationFrame";

const COLORS = ["#0f766e", "#d97706", "#2563eb", "#db2777", "#7c3aed", "#65a30d"];

function InvalidVisualization({ label, error, source }: { label: string; error: string; source: string }) {
  return <VisualizationFrame title={label} source={source}><div className="visualization-error"><AlertTriangle size={17} /><span>{error}，已保留源内容。</span></div></VisualizationFrame>;
}

function VisualizationLoading() {
  return <div className="visualization-loading"><Loader2 size={16} className="animate-spin" />正在生成图表…</div>;
}

export function ChartBlock({ source, isStreaming = false }: { source: string; isStreaming?: boolean }) {
  // A streamed fenced block is valid Markdown before its JSON payload is complete.
  // Keep the visualization in a pending state until the assistant finishes it.
  if (isStreaming) return <VisualizationFrame title="数据图表" source={source}><VisualizationLoading /></VisualizationFrame>;
  try {
    const spec = parseChartSpec(source);
    const chart = spec.type === "bar" ? <BarChart data={spec.data}>{axes(spec)}{spec.series.map((item, index) => <Bar key={item.field} dataKey={item.field} name={item.name || item.field} fill={item.color || COLORS[index % COLORS.length]} radius={[4, 4, 0, 0]} />)}</BarChart>
      : spec.type === "line" ? <LineChart data={spec.data}>{axes(spec)}{spec.series.map((item, index) => <Line key={item.field} type="monotone" dataKey={item.field} name={item.name || item.field} stroke={item.color || COLORS[index % COLORS.length]} strokeWidth={2} dot={false} />)}</LineChart>
      : spec.type === "area" ? <AreaChart data={spec.data}>{axes(spec)}{spec.series.map((item, index) => <Area key={item.field} type="monotone" dataKey={item.field} name={item.name || item.field} stroke={item.color || COLORS[index % COLORS.length]} fill={item.color || COLORS[index % COLORS.length]} fillOpacity={0.2} strokeWidth={2} />)}</AreaChart>
      : spec.type === "scatter" ? <ScatterChart>{axes(spec)}{spec.series.map((item, index) => <Scatter key={item.field} data={spec.data} name={item.name || item.field} dataKey={item.field} fill={item.color || COLORS[index % COLORS.length]} />)}</ScatterChart>
      : <PieChart><Tooltip /><Legend />{spec.series.map((item, seriesIndex) => <Pie key={item.field} data={spec.data} dataKey={item.field} nameKey={spec.x?.field || "name"} name={item.name || item.field} outerRadius={82} cx={seriesIndex ? "68%" : "32%"}>{spec.data.map((_, index) => <Cell key={index} fill={COLORS[index % COLORS.length]} />)}</Pie>)}</PieChart>;
    return <VisualizationFrame title={spec.title || "数据图表"} source={source}>
      {spec.description && <p className="visualization-description">{spec.description}</p>}
      <div className="chart-block"><ResponsiveContainer width="100%" height={280}>{chart}</ResponsiveContainer></div>
    </VisualizationFrame>;
  } catch (error) { return <InvalidVisualization label="数据图表" error={error instanceof Error ? error.message : "图表配置无效"} source={source} />; }
}

function axes(spec: ReturnType<typeof parseChartSpec>) {
  return <><CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} /><XAxis dataKey={spec.x?.field} name={spec.x?.label} tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} axisLine={false} tickLine={false} /><YAxis name={spec.y?.label} tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} axisLine={false} tickLine={false} /><Tooltip contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} labelStyle={{ color: "var(--text-secondary)" }} itemStyle={{ color: "var(--text-primary)" }} /><Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} /></>;
}

export function KpiBlock({ source, isStreaming = false }: { source: string; isStreaming?: boolean }) {
  if (isStreaming) return <VisualizationFrame title="数据摘要" source={source}><VisualizationLoading /></VisualizationFrame>;
  try {
    const spec = parseKpiSpec(source);
    const Trend = spec.trend === "up" ? TrendingUp : spec.trend === "down" ? TrendingDown : null;
    return <VisualizationFrame title="数据摘要" source={source}><div className="kpi-block"><span className="kpi-block__title">{spec.title}</span><strong>{spec.value}</strong>{spec.change && <span className={`kpi-block__change kpi-block__change--${spec.trend || "neutral"}`}>{Trend && <Trend size={14} />}{spec.change}</span>}{spec.description && <small>{spec.description}</small>}</div></VisualizationFrame>;
  } catch (error) { return <InvalidVisualization label="数据摘要" error={error instanceof Error ? error.message : "指标卡配置无效"} source={source} />; }
}

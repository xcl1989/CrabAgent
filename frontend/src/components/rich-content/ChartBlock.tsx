import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from "recharts";
import { AlertTriangle, TrendingDown, TrendingUp } from "lucide-react";
import { parseChartSpec, parseKpiSpec } from "./chartSchema";
import { VisualizationFrame } from "./VisualizationFrame";

const COLORS = ["#0f766e", "#d97706", "#2563eb", "#db2777", "#7c3aed", "#65a30d"];

function InvalidVisualization({ label, error, source }: { label: string; error: string; source: string }) {
  return <VisualizationFrame title={label} source={source}><div className="visualization-error"><AlertTriangle size={17} /><span>{error}，已保留源内容。</span></div></VisualizationFrame>;
}

export function ChartBlock({ source }: { source: string }) {
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
  return <><CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} /><XAxis dataKey={spec.x?.field} name={spec.x?.label} tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} axisLine={false} tickLine={false} /><YAxis name={spec.y?.label} tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} axisLine={false} tickLine={false} /><Tooltip /><Legend /></>;
}

export function KpiBlock({ source }: { source: string }) {
  try {
    const spec = parseKpiSpec(source);
    const Trend = spec.trend === "up" ? TrendingUp : spec.trend === "down" ? TrendingDown : null;
    return <VisualizationFrame title="数据摘要" source={source}><div className="kpi-block"><span className="kpi-block__title">{spec.title}</span><strong>{spec.value}</strong>{spec.change && <span className={`kpi-block__change kpi-block__change--${spec.trend || "neutral"}`}>{Trend && <Trend size={14} />}{spec.change}</span>}{spec.description && <small>{spec.description}</small>}</div></VisualizationFrame>;
  } catch (error) { return <InvalidVisualization label="数据摘要" error={error instanceof Error ? error.message : "指标卡配置无效"} source={source} />; }
}

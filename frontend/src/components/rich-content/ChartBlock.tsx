import { cloneElement, memo, useCallback, type ReactElement } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart,
  Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from "recharts";
import { AlertTriangle, Loader2, TrendingDown, TrendingUp } from "lucide-react";
import { parseChartSpec, parseKpiSpec, type CrabChartSpec, type CrabKpiSpec } from "./chartSchema";
import { VisualizationFrame } from "./VisualizationFrame";
import { MeasuredChartContainer } from "../charts/MeasuredChartContainer";
import { useStableVisualization } from "./stableVisualization";

const COLORS = ["#0f766e", "#d97706", "#2563eb", "#db2777", "#7c3aed", "#65a30d"];

function InvalidVisualization({ label, error, source }: { label: string; error: string; source: string }) {
  return <VisualizationFrame title={label} source={source}><div className="visualization-error"><AlertTriangle size={17} /><span>{error}，已保留源内容。</span></div></VisualizationFrame>;
}

function VisualizationLoading() {
  return <div className="visualization-loading"><Loader2 size={16} className="animate-spin" />正在生成图表…</div>;
}

function stableChartSpec(source: string) {
  return parseChartSpec(source);
}

function stableKpiSpec(source: string) {
  return parseKpiSpec(source);
}

export function ChartBlock({ source, isStreaming = false }: { source: string; isStreaming?: boolean }) {
  const parse = useCallback(stableChartSpec, []);
  const { candidate, stable } = useStableVisualization(source, parse);
  const spec = stable?.value;

  if (!candidate && !isStreaming) {
    return <InvalidVisualization label="数据图表" error="图表配置无效" source={source} />;
  }
  if (!spec) {
    return <VisualizationFrame title="数据图表" source={source}><VisualizationLoading /></VisualizationFrame>;
  }

  // The frame may update with prose deltas, but this memoized chart only sees a
  // new spec reference when the parsed visualization payload actually changes.
  return <VisualizationFrame title={spec.title || "数据图表"} source={source}>
    {spec.description && <p className="visualization-description">{spec.description}</p>}
    <ChartCanvas spec={spec} />
    {!candidate && isStreaming && <span className="sr-only">图表数据已保持为最后一个有效版本</span>}
  </VisualizationFrame>;
}

const ChartCanvas = memo(function ChartCanvas({ spec }: { spec: CrabChartSpec }) {
  const chart = chartElement(spec);
  return <div className="chart-block"><MeasuredChartContainer height={280}>{({ width, height }) => cloneChart(chart, width, height)}</MeasuredChartContainer></div>;
});

function cloneChart(chart: ReactElement<{ width?: number; height?: number }>, width: number, height: number) {
  return cloneElement(chart, { width, height });
}

function chartElement(spec: CrabChartSpec): ReactElement<{ width?: number; height?: number }> {
  if (spec.type === "bar") return <BarChart data={spec.data}>{axes(spec)}{spec.series.map((item, index) => <Bar key={item.field} dataKey={item.field} name={item.name || item.field} fill={item.color || COLORS[index % COLORS.length]} radius={[4, 4, 0, 0]} />)}</BarChart>;
  if (spec.type === "line") return <LineChart data={spec.data}>{axes(spec)}{spec.series.map((item, index) => <Line key={item.field} type="monotone" dataKey={item.field} name={item.name || item.field} stroke={item.color || COLORS[index % COLORS.length]} strokeWidth={2} dot={false} />)}</LineChart>;
  if (spec.type === "area") return <AreaChart data={spec.data}>{axes(spec)}{spec.series.map((item, index) => <Area key={item.field} type="monotone" dataKey={item.field} name={item.name || item.field} stroke={item.color || COLORS[index % COLORS.length]} fill={item.color || COLORS[index % COLORS.length]} fillOpacity={0.2} strokeWidth={2} />)}</AreaChart>;
  if (spec.type === "scatter") return <ScatterChart>{axes(spec)}{spec.series.map((item, index) => <Scatter key={item.field} data={spec.data} name={item.name || item.field} dataKey={item.field} fill={item.color || COLORS[index % COLORS.length]} />)}</ScatterChart>;
  return <PieChart><Tooltip /><Legend />{spec.series.map((item, seriesIndex) => <Pie key={item.field} data={spec.data} dataKey={item.field} nameKey={spec.x?.field || "name"} name={item.name || item.field} outerRadius={82} cx={seriesIndex ? "68%" : "32%"}>{spec.data.map((_, index) => <Cell key={index} fill={COLORS[index % COLORS.length]} />)}</Pie>)}</PieChart>;
}

function axes(spec: CrabChartSpec) {
  return <><CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} /><XAxis dataKey={spec.x?.field} name={spec.x?.label} tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} axisLine={false} tickLine={false} /><YAxis name={spec.y?.label} tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} axisLine={false} tickLine={false} /><Tooltip contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} labelStyle={{ color: "var(--text-secondary)" }} itemStyle={{ color: "var(--text-primary)" }} /><Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} /></>;
}

export function KpiBlock({ source, isStreaming = false }: { source: string; isStreaming?: boolean }) {
  const parse = useCallback(stableKpiSpec, []);
  const { candidate, stable } = useStableVisualization(source, parse);
  const spec = stable?.value;

  if (!candidate && !isStreaming) {
    return <InvalidVisualization label="数据摘要" error="指标卡配置无效" source={source} />;
  }
  if (!spec) {
    return <VisualizationFrame title="数据摘要" source={source}><VisualizationLoading /></VisualizationFrame>;
  }

  return <VisualizationFrame title="数据摘要" source={source}><KpiContent spec={spec} /></VisualizationFrame>;
}

const KpiContent = memo(function KpiContent({ spec }: { spec: CrabKpiSpec }) {
  const Trend = spec.trend === "up" ? TrendingUp : spec.trend === "down" ? TrendingDown : null;
  return <div className="kpi-block"><span className="kpi-block__title">{spec.title}</span><strong>{spec.value}</strong>{spec.change && <span className={`kpi-block__change kpi-block__change--${spec.trend || "neutral"}`}>{Trend && <Trend size={14} />}{spec.change}</span>}{spec.description && <small>{spec.description}</small>}</div>;
});

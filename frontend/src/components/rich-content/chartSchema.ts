export type ChartType = "bar" | "line" | "area" | "pie" | "scatter";

export interface ChartSeries {
  field: string;
  name?: string;
  color?: string;
}

export interface CrabChartSpec {
  version: 1;
  type: ChartType;
  title?: string;
  description?: string;
  x?: { field: string; label?: string };
  y?: { label?: string };
  series: ChartSeries[];
  data: Array<Record<string, string | number | null>>;
}

export interface CrabKpiSpec {
  version: 1;
  title: string;
  value: string | number;
  change?: string;
  trend?: "up" | "down" | "neutral";
  description?: string;
}

const MAX_DATA_ROWS = 200;
const MAX_SERIES = 20;
const SAFE_COLOR = /^(#[0-9a-f]{3,8}|rgb\([\d\s,.%]+\)|hsl\([\d\s,.%]+\))$/i;

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function parseJson(source: string): unknown {
  try {
    return JSON.parse(source);
  } catch {
    throw new Error("JSON 格式无效");
  }
}

function text(value: unknown, field: string, required = false): string | undefined {
  if (value == null && !required) return undefined;
  if (typeof value !== "string" || !value.trim() || value.length > 160) {
    throw new Error(`${field} 必须是长度不超过 160 的文本`);
  }
  return value;
}

export function parseChartSpec(source: string): CrabChartSpec {
  const raw = parseJson(source);
  if (!isRecord(raw) || raw.version !== 1) throw new Error("仅支持 version: 1 的图表");
  if (!(["bar", "line", "area", "pie", "scatter"] as string[]).includes(String(raw.type))) {
    throw new Error("不支持的图表类型");
  }
  if (!Array.isArray(raw.series) || raw.series.length === 0 || raw.series.length > MAX_SERIES) {
    throw new Error(`series 必须包含 1-${MAX_SERIES} 个系列`);
  }
  if (!Array.isArray(raw.data) || raw.data.length === 0 || raw.data.length > MAX_DATA_ROWS) {
    throw new Error(`data 必须包含 1-${MAX_DATA_ROWS} 行数据`);
  }
  const x = raw.x;
  const seriesFields = raw.series
    .filter(isRecord)
    .map((item) => item.field)
    .filter((field): field is string => typeof field === "string");
  const explicitXField = isRecord(x) ? text(x.field, "x.field") : undefined;
  // Older or less precise model replies may omit x.field. Infer a text category
  // column from the data instead of rejecting an otherwise safe chart payload.
  const inferredXField = raw.type === "pie" ? undefined : raw.data
    .flatMap((row) => isRecord(row) ? Object.entries(row) : [])
    .find(([key, value]) => !seriesFields.includes(key) && typeof value === "string")?.[0];
  const xField = explicitXField || inferredXField;
  if (raw.type !== "pie" && !xField) throw new Error("除饼图外必须提供 x.field，或在数据中包含文本分类字段");

  return {
    version: 1,
    type: raw.type as ChartType,
    title: text(raw.title, "title"),
    description: text(raw.description, "description"),
    x: xField ? { field: xField, label: isRecord(x) ? text(x.label, "x.label") : undefined } : undefined,
    y: isRecord(raw.y) ? { label: text(raw.y.label, "y.label") } : undefined,
    series: raw.series.map((item, index) => {
      if (!isRecord(item)) throw new Error(`series[${index}] 无效`);
      const color = text(item.color, `series[${index}].color`);
      if (color && !SAFE_COLOR.test(color)) throw new Error("颜色仅支持 #hex、rgb() 或 hsl()");
      return { field: text(item.field, `series[${index}].field`, true)!, name: text(item.name, `series[${index}].name`), color };
    }),
    data: raw.data.map((row, index) => {
      if (!isRecord(row)) throw new Error(`data[${index}] 无效`);
      const clean: Record<string, string | number | null> = {};
      for (const [key, value] of Object.entries(row)) {
        if (key.length > 80 || !["string", "number"].includes(typeof value) && value !== null) {
          throw new Error(`data[${index}] 包含无效字段`);
        }
        clean[key] = value as string | number | null;
      }
      return clean;
    }),
  };
}

export function parseKpiSpec(source: string): CrabKpiSpec {
  const raw = parseJson(source);
  if (!isRecord(raw) || raw.version !== 1) throw new Error("仅支持 version: 1 的指标卡");
  if (typeof raw.value !== "string" && typeof raw.value !== "number") throw new Error("value 必须是文本或数字");
  const trend = raw.trend;
  if (trend != null && trend !== "up" && trend !== "down" && trend !== "neutral") throw new Error("trend 必须是 up、down 或 neutral");
  return { version: 1, title: text(raw.title, "title", true)!, value: raw.value, change: text(raw.change, "change"), trend: trend || undefined, description: text(raw.description, "description") };
}

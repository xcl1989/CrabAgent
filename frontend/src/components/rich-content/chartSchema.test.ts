import { describe, expect, it } from "vitest";
import { parseChartSpec, parseKpiSpec } from "./chartSchema";

describe("parseChartSpec", () => {
  it("accepts the current object series format", () => {
    const chart = parseChartSpec(JSON.stringify({
      version: 1, type: "bar", x: { field: "month" },
      series: [{ field: "revenue", name: "收入" }],
      data: [{ month: "1月", revenue: 120 }],
    }));
    expect(chart.x?.field).toBe("month");
    expect(chart.series[0]).toEqual({ field: "revenue", name: "收入", color: undefined });
  });

  it("renders historical xField and string-series messages", () => {
    const chart = parseChartSpec(JSON.stringify({
      version: 1, type: "bar", xField: "month", series: ["收入"],
      data: [{ month: "1月", 收入: 120 }],
    }));
    expect(chart.x?.field).toBe("month");
    expect(chart.series[0].field).toBe("收入");
  });

  it("infers a text category field when x is omitted", () => {
    const chart = parseChartSpec(JSON.stringify({
      version: 1, type: "line", series: ["revenue"],
      data: [{ month: "1月", revenue: 120 }],
    }));
    expect(chart.x?.field).toBe("month");
  });

  it("rejects executable or oversized data", () => {
    expect(() => parseChartSpec(JSON.stringify({
      version: 1, type: "bar", series: ["revenue"],
      data: [{ month: "1月", revenue: { value: 120 } }],
    }))).toThrow("无效字段");
  });
});

describe("parseKpiSpec", () => {
  it("accepts a valid KPI", () => {
    expect(parseKpiSpec(JSON.stringify({ version: 1, title: "转化率", value: "18.6%", trend: "up" }))).toMatchObject({ title: "转化率", trend: "up" });
  });
});

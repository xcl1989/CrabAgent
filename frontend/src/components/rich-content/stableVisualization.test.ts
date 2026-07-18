import { describe, expect, it } from "vitest";
import { keepStableVisualization } from "./stableVisualization";

describe("keepStableVisualization", () => {
  it("retains the previous parsed visualization when the next stream chunk is incomplete", () => {
    const current = { key: '{"version":1}', value: { version: 1 } };

    expect(keepStableVisualization(current, null)).toBe(current);
  });

  it("retains the existing object when a later stream chunk has equivalent visualization data", () => {
    const current = { key: '{"version":1}', value: { version: 1 } };
    const equivalent = { key: '{"version":1}', value: { version: 1 } };

    expect(keepStableVisualization(current, equivalent)).toBe(current);
  });

  it("replaces the visualization only when its parsed data changes", () => {
    const current = { key: '{"version":1}', value: { version: 1 } };
    const updated = { key: '{"version":2}', value: { version: 2 } };

    expect(keepStableVisualization(current, updated)).toBe(updated);
  });
});

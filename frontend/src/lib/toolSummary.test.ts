import { describe, expect, it } from "vitest";
import { getToolSummary } from "./toolSummary";

describe("tool call summaries", () => {
  it("prefers the model summary over the first business argument", () => {
    expect(getToolSummary(JSON.stringify({ name: "edit", arguments: {
      file_path: "/tmp/file", summary: "Update field mappings",
    } }))).toEqual({ name: "edit", summary: "Update field mappings" });
  });

  it("still renders the legacy underscore key from older sessions", () => {
    expect(getToolSummary(JSON.stringify({ name: "edit", arguments: {
      file_path: "/tmp/file", _summary: "Legacy caption",
    } }))).toEqual({ name: "edit", summary: "Legacy caption" });
  });

  it("normalizes and bounds the displayed summary", () => {
    const summary = getToolSummary(JSON.stringify({ arguments: {
      summary: `  Review\n changes ${"x".repeat(100)}`,
    } })).summary;
    expect(summary).toHaveLength(40);
    expect(summary.startsWith("Review changes ")).toBe(true);
  });

  it.each([undefined, "", "   ", 42, null])("falls back for absent or invalid metadata: %s", (summary) => {
    expect(getToolSummary(JSON.stringify({ name: "bash", arguments: {
      summary, command: "pwd",
    } }))).toEqual({ name: "bash", summary: "pwd" });
  });

  it("handles empty arguments and malformed content", () => {
    expect(getToolSummary('{"name":"noop","arguments":{}}').summary).toBe("");
    expect(getToolSummary("bad json")).toEqual({ name: "unknown", summary: "bad json" });
  });
});

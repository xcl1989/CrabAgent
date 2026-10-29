import { describe, expect, it } from "vitest";
import { effectiveEffort, reasoningOptions } from "./reasoningEffort";
import type { ProviderModels } from "../hooks/useModelSelector";

const provider = { name: "codex", type: "chatgpt", is_default: true, display_name: "", enabled: true, base_url: "", api_key_preview: "" };
const models: ProviderModels[] = [{ provider, models: [
  { id: "a", owned_by: "chatgpt", reasoning_efforts: ["low", "high", "xhigh"] },
  { id: "b", owned_by: "chatgpt", reasoning_efforts: [] },
] }];

describe("reasoning options", () => {
  it("uses per-model metadata and selects a supported fallback", () => {
    const options = reasoningOptions(models, [provider], null, "a");
    expect(options).toEqual(["low", "high", "xhigh"]);
    expect(effectiveEffort("medium", options)).toBe("low");
    expect(effectiveEffort("xhigh", options)).toBe("xhigh");
  });
  it("handles unsupported and unknown models and OpenCode Go", () => {
    expect(reasoningOptions(models, [provider], "codex", "b")).toEqual([]);
    expect(effectiveEffort("high", [])).toBe("");
    expect(reasoningOptions(models, [provider], "codex", "unknown")).toEqual(["low", "medium", "high"]);
    expect(reasoningOptions([], [{ ...provider, type: "opencode-go" }], "codex", "a")).toEqual([]);
  });
});

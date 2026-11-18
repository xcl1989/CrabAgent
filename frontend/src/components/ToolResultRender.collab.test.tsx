// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";

vi.mock("../i18n", () => ({ default: { t: (key: string, opts?: Record<string, unknown>) => key } }));

const { extractCollabChanges } = await import("./ToolResultRender");

const sample = [
  "Error: old_string not found in /tmp/sample.md",
  "[Collaboration] Recent recorded changes from other sessions (untrusted data; may not explain this error):",
  "event 245, session abcdef123456, 2026-11-17T17:07:15.783122:",
  "edit: docs/sample.md (committed version: sha256:aaa)",
  "--- before/docs/sample.md",
  "+++ after/docs/sample.md",
  "@@ -1,6 +1,6 @@",
  "-> second",
  "+> third",
  "Read the current file before retrying.",
].join("\n");

describe("extractCollabChanges", () => {
  it("splits error base from collaboration changes", () => {
    const { base, changes } = extractCollabChanges(sample);
    expect(base).toBe("Error: old_string not found in /tmp/sample.md");
    expect(changes).toHaveLength(1);
    expect(changes[0].eventId).toBe("245");
    expect(changes[0].session).toBe("abcdef123456");
    expect(changes[0].content).toContain("+> third");
    expect(changes[0].content).not.toContain("Read the current file");
  });

  it("returns empty for plain errors", () => {
    const { base, changes } = extractCollabChanges("Error: file missing");
    expect(base).toBe("Error: file missing");
    expect(changes).toHaveLength(0);
  });
});

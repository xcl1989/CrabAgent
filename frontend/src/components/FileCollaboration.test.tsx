// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { FileCollaboration } from "./FileCollaboration";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("../api/client", () => ({ api: { get: mocks.get } }));

it("skips ordinary sessions and fetches full diffs only on demand", async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const row = { id: 1, session: "session-a", branch: "main", scope: "app.ts", summary: "Update parser" };
  mocks.get.mockImplementation(async (_url, query) => ({
    intentions: [row],
    changes: [{ ...row, id: 2, summary: "Lines 5–8", ...(query.include_diff ? { diff: "+updated" } : {}) }],
  }));
  const element = document.createElement("div");
  document.body.append(element);
  const root = createRoot(element);
  try {
    await act(async () => root.render(<FileCollaboration enabled={false} sessionId="b" path="app.ts" />));
    expect(mocks.get).not.toHaveBeenCalled();
    await act(async () => root.render(<FileCollaboration enabled sessionId="b" path="app.ts" />));
    expect(mocks.get).toHaveBeenLastCalledWith("/collaboration/sessions/b/file-activity", { path: "app.ts" });
    expect(element.textContent).toContain("Update parser");
    expect(element.textContent).toContain("Lines 5–8");
    expect(element.textContent).not.toContain("+updated");
    await act(async () => {
      const details = element.querySelector("details")!;
      details.open = true;
      details.dispatchEvent(new Event("toggle"));
    });
    expect(mocks.get).toHaveBeenLastCalledWith("/collaboration/sessions/b/file-activity", { path: "app.ts", include_diff: "true" });
    expect(element.textContent).toContain("+updated");
    await act(async () => root.render(<FileCollaboration enabled={false} sessionId="b" path="app.ts" />));
    expect(element.textContent).toBe("");
  } finally {
    await act(async () => root.unmount());
    element.remove();
  }
});

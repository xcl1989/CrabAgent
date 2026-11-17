// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { useExternalFileVersion } from "./useExternalFileVersion";

const mocks = vi.hoisted(() => ({ getFileVersion: vi.fn() }));
vi.mock("../api/files", () => ({ getFileVersion: mocks.getFileVersion }));
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks(); });

function Probe({ path, version }: { path: string; version: string }) {
  const changed = useExternalFileVersion(path, version);
  return <div>{changed ? "changed" : "unchanged"}</div>;
}

it("warns about an externally modified file without replacing the editing version", async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
  mocks.getFileVersion.mockResolvedValue("version-new");
  const element = document.createElement("div");
  document.body.append(element);
  const root = createRoot(element);
  await act(async () => { root.render(<Probe path="doc.md" version="version-old" />); });
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(mocks.getFileVersion).toHaveBeenCalledWith("doc.md", false);
  expect(element.textContent).toBe("changed");
  await act(async () => { root.unmount(); });
  element.remove();
});

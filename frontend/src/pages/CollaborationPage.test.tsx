// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import CollaborationPage from "./CollaborationPage";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), info: vi.fn() }));
vi.mock("../api/client", () => ({ api: { get: mocks.get, post: mocks.post } }));
vi.mock("sonner", () => ({ toast: { info: mocks.info } }));

it("binds the current session to a selected project", async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  mocks.get.mockImplementation(async (path: string) => path.endsWith("/projects")
    ? [{ id: 1, name: "Project", workspace: "/project" }] : []);
  mocks.post.mockResolvedValue({ status: "ok" });
  const element = document.createElement("div");
  document.body.append(element);
  const root = createRoot(element);
  await act(async () => { root.render(<CollaborationPage sessionId="session-a" />); });
  await act(async () => { [...element.querySelectorAll("button")].find((button) => button.textContent === "Project")!.click(); });
  await act(async () => { [...element.querySelectorAll("button")].find((button) => button.textContent === "绑定当前对话")!.click(); });
  expect(mocks.post).toHaveBeenCalledWith("/collaboration/projects/1/bind", { session_id: "session-a" });
  expect(element.textContent).toContain("/project");
  await act(async () => { root.unmount(); });
  element.remove();
});

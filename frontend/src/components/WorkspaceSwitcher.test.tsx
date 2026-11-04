// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import WorkspaceSwitcher from "./WorkspaceSwitcher";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../api/sessions", () => ({
  getCurrentWorkspace: vi.fn().mockResolvedValue({ workspace: "/home/default" }),
  listWorkspaces: vi.fn().mockResolvedValue([{ workspace: "/projects/alpha", session_count: 1, hidden: false }]),
  reorderWorkspaces: vi.fn(), updateWorkspacePreference: vi.fn(),
}));
vi.mock("../api/monitor", () => ({ getAgentMonitor: vi.fn().mockResolvedValue([]) }));
vi.mock("../api/work", () => ({ getAttentionByWorkspace: vi.fn().mockResolvedValue({ workspaces: [] }) }));
vi.mock("./DirectoryPicker", () => ({ default: () => null }));
vi.mock("./ui/Modal", () => ({ Modal: () => null }));

afterEach(() => { document.body.innerHTML = ""; });

it("renders outside a clipped toolbar, tracks scrolling, and switches workspaces", async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const toolbar = document.createElement("div");
  toolbar.style.overflowX = "auto";
  document.body.append(toolbar);
  const root = createRoot(toolbar);
  const onChange = vi.fn();
  await act(async () => root.render(<WorkspaceSwitcher current="" onChange={onChange} />));
  const trigger = toolbar.querySelector("button")!;
  let left = 100;
  vi.spyOn(trigger.parentElement!, "getBoundingClientRect").mockImplementation(() => ({ left, bottom: 60 } as DOMRect));
  await act(async () => trigger.click());
  const choice = [...document.body.querySelectorAll("button")].find((button) => button.textContent?.includes("alpha"))!;
  const menu = choice.parentElement!;
  expect(toolbar.contains(menu)).toBe(false);
  expect(menu.parentElement).toBe(document.body);
  expect(menu.className).toContain("fixed");
  expect(menu.style.left).toBe("100px");
  left = 40;
  await act(async () => toolbar.dispatchEvent(new Event("scroll")));
  expect(menu.style.left).toBe("40px");
  await act(async () => {
    choice.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    choice.click();
  });
  expect(onChange).toHaveBeenCalledWith("/projects/alpha");
  expect(document.body.contains(menu)).toBe(false);
  await act(async () => trigger.click());
  await act(async () => document.body.dispatchEvent(new MouseEvent("mousedown", { bubbles: true })));
  expect(document.body.querySelectorAll(".fixed")).toHaveLength(0);
  await act(async () => root.unmount());
});

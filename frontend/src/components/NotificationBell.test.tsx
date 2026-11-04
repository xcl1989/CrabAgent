// @vitest-environment jsdom
// 回归测试：通知面板迁移到 portal 后，点击面板内容不得被外点关闭逻辑误判。
// 曾因 mousedown handler 只排除铃铛按钮，未排除 portal 面板，导致面板内容点不到。
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import NotificationBell from "./NotificationBell";
import type { Notification } from "../api/notifications";

vi.mock("../api/notifications", () => ({
  listNotifications: vi.fn(async () => [
    {
      id: 1,
      title: "监控任务完成",
      body: "任务执行完成",
      read: false,
      created_at: "2026-11-04T10:00:00Z",
      conversation_id: "sess-1",
    } satisfies Notification,
  ]),
  unreadCount: vi.fn(async () => ({ count: 1 })),
  markRead: vi.fn(async () => ({ status: "ok" })),
  markAllRead: vi.fn(async () => ({ status: "ok" })),
}));

vi.mock("../hooks/useWorkStatus", () => ({
  useWorkStatus: () => ({ connected: true }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) =>
      typeof fallback === "string" ? fallback : key,
  }),
}));

let container: HTMLDivElement;
let root: Root;

function renderBell() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root.render(
      <NotificationBell onSwitchSession={vi.fn()} onNotificationAction={vi.fn()} />,
    );
  });
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.clearAllMocks();
});

async function openPanel() {
  const bell = container.querySelector("button")!;
  await act(async () => {
    bell.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  // 等待 fetchList 后的渲染
  await act(async () => {
    await Promise.resolve();
  });
}

describe("NotificationBell portal panel", () => {
  it("keeps the panel open when clicking inside it", async () => {
    renderBell();
    await openPanel();

    const panel = document.querySelector("body > .fixed") as HTMLElement;
    expect(panel).toBeTruthy();

    // 模拟面板内一次完整点击（mousedown → mouseup → click）
    const card = panel.querySelector(".cursor-pointer") as HTMLElement;
    expect(card).toBeTruthy();
    await act(async () => {
      card.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    });
    await act(async () => {
      await Promise.resolve();
    });

    // 关键断言：面板不能因为面板内的 mousedown 而被关闭
    expect(document.querySelector("body > .fixed")).not.toBeNull();
  });

  it("closes the panel on mousedown outside the bell and panel", async () => {
    renderBell();
    await openPanel();
    expect(document.querySelector("body > .fixed")).not.toBeNull();

    await act(async () => {
      document.body.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    });
    expect(document.querySelector("body > .fixed")).toBeNull();
  });
});

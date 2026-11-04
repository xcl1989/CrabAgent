import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import AgentsPage from "./AgentsPage";
import CalendarPage, { MobileAgenda } from "./CalendarPage";
import type { CalendarEvent } from "../api/calendar";

vi.mock("../api/client", () => ({ api: {} }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

describe("mobile page layouts", () => {
  it("starts with the agent list and hides details on narrow screens", () => {
    const html = renderToStaticMarkup(<AgentsPage />);
    expect(html).toContain("w-full md:w-64 lg:w-72");
    expect(html).toContain("hidden md:block");
  });
  it("provides a mobile agenda and overview", () => {
    const html = renderToStaticMarkup(<CalendarPage />);
    expect(html).toContain('aria-label="日程列表"');
    expect(html).toContain("hidden md:flex");
    expect(html).toContain("今日概览");
    expect(html).toContain('aria-label="日历设置"');
  });
  it("sorts and filters the agenda and shows empty and loading states", () => {
    const events = [
      { id: 2, title: "Later", type: "manual", start_time: "2025-05-02T11:00:00" },
      { id: 1, title: "Earlier", type: "manual", start_time: "2025-05-01T09:00:00", all_day: true },
      { id: 3, title: "Outside", type: "manual", start_time: "2025-06-01T09:00:00" },
    ] as CalendarEvent[];
    const props = { events, rangeStart: "2025-05-01", rangeEnd: "2025-05-31", onEventClick: vi.fn() };
    const html = renderToStaticMarkup(<MobileAgenda {...props} loading={false} />);
    expect(html.indexOf("Earlier")).toBeLessThan(html.indexOf("Later"));
    expect(html).not.toContain("Outside");
    expect(html).toContain("全天");
    expect(renderToStaticMarkup(<MobileAgenda {...props} events={[]} loading={false} />)).toContain("此时段没有事件");
    expect(renderToStaticMarkup(<MobileAgenda {...props} events={[]} loading />)).toContain("加载中...");
  });
});

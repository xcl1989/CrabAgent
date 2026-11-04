import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MobileSessionCard } from "./UsagePage";
import type { SessionUsage } from "../api/tokenUsage";
vi.mock("../api/client", () => ({ api: {} }));


const session = { session_id: "abc", title: "Mobile session", total_tokens: 1200, prompt_tokens: 800, completion_tokens: 400, cache_hit_rate: 0.5, calls: 4, last_active: "2025-05-02T11:00:00Z" } as SessionUsage;
const props = { session, detail: null, detailLoading: false, onToggle: vi.fn(), t: (key: string) => key };
describe("mobile usage card", () => {
  it("shows metrics and accessible collapsed state", () => {
    const html = renderToStaticMarkup(<MobileSessionCard {...props} expanded={false} />);
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain("Mobile session");
    expect(html).toContain("1.2K");
    expect(html).toContain("50%");
  });
  it("shows loading and empty detail states", () => {
    expect(renderToStaticMarkup(<MobileSessionCard {...props} expanded detailLoading />)).toContain("common.loading");
    expect(renderToStaticMarkup(<MobileSessionCard {...props} expanded />)).toContain("usage.noData");
  });
});

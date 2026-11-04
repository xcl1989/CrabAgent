// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SessionList from "./SessionList";
import type { Session } from "../api/sessions";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../api/sessions", () => ({ searchSessions: vi.fn().mockResolvedValue([]) }));
vi.mock("../api/time", () => ({ formatDate: () => "2025-01-01" }));

const sessions: Session[] = [
  { session_id: "s1", title: "First chat", workspace: "w", model: "m", provider: "p", agent: "default", active_branch: "main", prompt_locale: "", history_searchable: true, created_at: null, updated_at: "2025-01-01T00:00:00" },
  { session_id: "s2", title: "Second chat", workspace: "w", model: "m", provider: "p", agent: "default", active_branch: "main", prompt_locale: "", history_searchable: true, created_at: null, updated_at: "2025-01-02T00:00:00" },
  { session_id: "s3", title: "Third chat", workspace: "w", model: "m", provider: "p", agent: "default", active_branch: "main", prompt_locale: "", history_searchable: true, created_at: null, updated_at: "2025-01-03T00:00:00" },
];

const baseProps = {
  sessions,
  activeId: "s1",
  onSelect: vi.fn(),
  onNew: vi.fn(),
  onDelete: vi.fn(),
  onToggleHistorySearchable: vi.fn(),
  onOpenProviders: vi.fn(),
  onOpenMcpServers: vi.fn(),
  onOpenScheduledTasks: vi.fn(),
  onOpenTasks: vi.fn(),
  onOpenEmail: vi.fn(),
  onOpenSkills: vi.fn(),
};

let container: HTMLDivElement;
let root: Root;
async function render(node: React.ReactNode) { await act(async () => { root.render(node); }); }
async function click(el: HTMLElement) { await act(async () => { el.click(); }); }
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  Object.values(baseProps).forEach((fn) => { if (typeof fn === "function") (fn as ReturnType<typeof vi.fn>).mockClear(); });
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });

describe("SessionList mobile drawer new-chat entry", () => {
  it("shows the new-chat button in the mobile drawer header and creates a session on click", async () => {
    const onClose = vi.fn();
    await render(<SessionList {...baseProps} mobileOpen onMobileClose={onClose} />);
    const drawer = container.querySelector(".fixed.w-72")!;
    expect(drawer).not.toBeNull();
    const newBtn = drawer.querySelector<HTMLButtonElement>('[aria-label="session.newChat"]');
    expect(newBtn).not.toBeNull();
    // Button sits in the mobile header, at the top of the drawer (above search + list)
    const header = newBtn!.closest("div")!;
    expect(header.className).toContain("md:hidden");
    expect(header.compareDocumentPosition(drawer.querySelector(".flex-1.overflow-y-auto")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await click(newBtn!);
    expect(baseProps.onNew).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("keeps the desktop header new-chat button and desktop-only wrapper intact when drawer is closed", async () => {
    await render(<SessionList {...baseProps} />);
    // No mobile drawer overlay is rendered
    expect(container.querySelector(".fixed.w-72")).toBeNull();
    const newBtns = container.querySelectorAll('button[title^="session.newChat"]');
    // Both mobile and desktop headers exist in the sidebar tree; the desktop
    // header (hidden md:flex) keeps its original new-chat button untouched
    expect(newBtns.length).toBe(2);
    const desktopBtn = [...newBtns].find((b) => b.closest("div")!.className.includes("hidden md:flex"))!;
    expect(desktopBtn).toBeTruthy();
    expect(desktopBtn.getAttribute("aria-label")).toBeNull();
    // Sidebar is hidden below md as before
    expect(container.innerHTML).toContain("hidden md:contents");
  });
});

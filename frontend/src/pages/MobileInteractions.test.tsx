// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SettingsPage from "./SettingsPage";
import AgentsPage from "./AgentsPage";
import CalendarPage from "./CalendarPage";
import ChatInput from "../components/ChatInput";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
const mocks = vi.hoisted(() => ({ save: vi.fn(), cache: vi.fn() }));
vi.mock("../hooks/useSettingsData", () => ({ useSettingsData: () => ({
  settings: mockSettings,
  providerModels: [], settingsLoading: false, providersLoading: true, updateSettings: mocks.cache,
}) }));
const mockSettings = { default_model: "", default_model_provider: "", searxng_url: "old", proxy: "", web_proxy: "", llm_proxy: "", browser_proxy: "", sub_agent_model_map: "", conversation_history_tool_enabled: "false" };
vi.mock("../api/client", () => ({ api: {} }));
vi.mock("../api/settings", () => ({ updateSettings: mocks.save }));
vi.mock("../components/PushPanel", () => ({ default: () => <div>Push panel</div> }));
vi.mock("../components/ui/Toast", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("../api/agents", () => ({
  listAgentProfiles: vi.fn().mockResolvedValue([{ id: 1, name: "alpha", display_name: "Alpha", enabled: true, role: "Research", goal: "", backstory: "", model: "", tools: [], tool_permissions: {} }]),
  listLearningAgents: vi.fn().mockResolvedValue([]), listTools: vi.fn().mockResolvedValue([]), getDefaultToolPermissions: vi.fn().mockResolvedValue({}),
}));
vi.mock("../api/calendar", () => ({ calendarApi: { listEvents: vi.fn().mockResolvedValue([]), getToday: vi.fn().mockResolvedValue({ events: [], free_slots: [], summary: "Today" }), listIcalSources: vi.fn().mockResolvedValue([]) } }));

let container: HTMLDivElement;
let root: Root;
async function render(node: React.ReactNode) { await act(async () => { root.render(node); }); }
function button(text: string) { const found = [...container.querySelectorAll("button")].find((b) => b.textContent?.trim() === text); if (!found) throw new Error(`Missing button: ${text}`); return found; }
async function click(el: HTMLElement) { await act(async () => { el.click(); }); }
async function value(el: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, next: string) {
  const proto = el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, next);
  await act(async () => { el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? "change" : "input", { bubbles: true })); });
}
beforeEach(() => { (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement("div"); document.body.append(container); root = createRoot(container); mocks.save.mockReset().mockResolvedValue({}); mocks.cache.mockReset(); });
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });

describe("mobile interaction flows", () => {
  it("switches settings categories, retains edits and saves them", async () => {
    await render(<SettingsPage />);
    const select = container.querySelector("select")!;
    await value(select, "search");
    const input = container.querySelector<HTMLInputElement>('input[placeholder="settingsPage.searxngUrlPlaceholder"]')!;
    expect(input.value).toBe("old");
    await value(input, "https://search.example");
    await value(select, "privacy");
    await value(select, "search");
    expect(container.querySelector<HTMLInputElement>('input[placeholder="settingsPage.searxngUrlPlaceholder"]')!.value).toBe("https://search.example");
    await click(button("settingsPage.save"));
    expect(mocks.save).toHaveBeenCalledWith(expect.objectContaining({ searxng_url: "https://search.example" }));
    expect(mocks.cache).toHaveBeenCalledWith(expect.objectContaining({ searxng_url: "https://search.example" }));
    await value(select, "push");
    expect([...container.querySelectorAll("button")].some((b) => b.textContent?.trim() === "settingsPage.save")).toBe(false);
  });
  it("does not update the settings cache when saving fails", async () => {
    mocks.save.mockRejectedValueOnce(new Error("Save failed"));
    await render(<SettingsPage />);
    await value(container.querySelector("select")!, "search");
    await value(container.querySelector<HTMLInputElement>('input[placeholder="settingsPage.searxngUrlPlaceholder"]')!, "https://search.example");
    await click(button("settingsPage.save"));
    expect(mocks.save).toHaveBeenCalledOnce();
    expect(mocks.cache).not.toHaveBeenCalled();
    expect(button("settingsPage.save").disabled).toBe(false);
  });
  it("opens agent details and returns to the list", async () => {
    await render(<AgentsPage />);
    const agent = [...container.querySelectorAll("button")].find((b) => b.textContent?.includes("Alpha"))!;
    const list = agent.closest(".w-full.md\\:w-64")!;
    expect(list.className).not.toContain("hidden md:flex");
    await click(agent);
    expect(list.className).toContain("hidden md:flex");
    await click(button("agentsPage.title"));
    expect(list.className).not.toContain("hidden md:flex");
  });
  it("switches calendar overview and returns to the agenda", async () => {
    await render(<CalendarPage />);
    const agenda = container.querySelector('[aria-label="日程列表"]')!;
    const main = agenda.closest(".min-w-0.flex-1.flex-col")!;
    await click(button("今日概览"));
    expect(main.className).toContain("hidden md:flex");
    await click(button("← 返回日历"));
    expect(main.className).not.toContain("hidden md:flex");
  });
  it("sends trimmed chat text, supports actions and abort", async () => {
    const send = vi.fn(), upload = vi.fn(), abort = vi.fn();
    const props = { sending: false, replaying: false, onSend: send, onAbort: abort, onFileUpload: upload, onFilePaste: vi.fn(), onDelegateOpen: vi.fn() };
    await render(<ChatInput {...props} />);
    const textarea = container.querySelector("textarea")!;
    const sendButton = container.querySelector<HTMLButtonElement>('[aria-label="common.send"]')!;
    expect(sendButton.disabled).toBe(true);
    await value(textarea, "  hello  ");
    await click(sendButton);
    expect(send).toHaveBeenCalledWith("hello");
    expect(textarea.value).toBe("");
    await value(textarea, "keyboard");
    await act(async () => { textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, shiftKey: true })); });
    expect(send).toHaveBeenCalledTimes(1);
    await act(async () => { textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
    expect(send).toHaveBeenLastCalledWith("keyboard");
    await click(container.querySelector<HTMLElement>('[aria-label="chat.attachFile"]')!);
    expect(upload).toHaveBeenCalledOnce();
    await render(<ChatInput {...props} sending />);
    await click(container.querySelector<HTMLElement>('[aria-label="common.stop"]')!);
    expect(abort).toHaveBeenCalledOnce();
  });
});

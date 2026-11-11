// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SkillsPanel from "./SkillsPanel";
import * as api from "../api/settings";
vi.mock("../api/settings", () => ({ getSkills: vi.fn(), getSkillDetail: vi.fn() }));
vi.mock("./ui", () => ({ Modal: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
const skills = [
  { name: "alpha", description: "First skill", location: "/alpha", auxiliary_files: ["guide.md"] },
  { name: "beta", description: "Second skill", location: "/beta", auxiliary_files: [] },
];
let container: HTMLDivElement;
let root: Root;
const button = (text: string) => [...container.querySelectorAll("button")].find((item) => item.textContent?.includes(text))!;
async function click(text: string) { await act(async () => button(text).click()); }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((r) => { resolve = r; }); return { promise, resolve }; }
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.resetAllMocks(); vi.mocked(api.getSkills).mockResolvedValue(skills);
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
async function render() { await act(async () => root.render(<SkillsPanel onClose={vi.fn()} />)); }
describe("SkillsPanel", () => {
  it("filters descriptions, renders markdown and raw content and lists auxiliary files", async () => {
    vi.mocked(api.getSkillDetail).mockResolvedValue({ ...skills[0], content: "# Heading\n\n**bold**" });
    await render(); const input = container.querySelector("input")!;
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "FIRST"); input.dispatchEvent(new Event("input", { bubbles: true })); });
    expect(button("alpha")).toBeTruthy(); expect(button("beta")).toBeUndefined();
    await click("alpha"); expect(container.querySelector("h1")?.textContent).toBe("Heading");
    expect(container.textContent).toContain("guide.md"); await click("Raw"); expect(container.querySelector("pre")?.textContent).toContain("# Heading");
    await click("Back to skills"); expect(container.querySelector('[aria-label="Skills list"]')?.className).not.toContain("hidden");
  });
  it("ignores out-of-order detail responses", async () => {
    const a = deferred<api.SkillDetail>(); const b = deferred<api.SkillDetail>();
    vi.mocked(api.getSkillDetail).mockImplementation((name) => name === "alpha" ? a.promise : b.promise);
    await render(); await click("alpha"); await click("beta");
    await act(async () => b.resolve({ ...skills[1], content: "Beta content" }));
    await act(async () => a.resolve({ ...skills[0], content: "Stale content" }));
    expect(container.textContent).toContain("Beta content"); expect(container.textContent).not.toContain("Stale content");
  });
  it("distinguishes list and detail errors and supports retry", async () => {
    vi.mocked(api.getSkills).mockRejectedValueOnce(new Error()).mockResolvedValueOnce(skills);
    vi.mocked(api.getSkillDetail).mockRejectedValueOnce(new Error()).mockResolvedValueOnce({ ...skills[0], content: "Recovered" });
    await render(); expect(container.textContent).toContain("Failed to load skills");
    await click("Retry"); await click("alpha"); expect(container.textContent).toContain("Failed to load skill detail");
    await click("Retry"); expect(container.textContent).toContain("Recovered");
  });
});

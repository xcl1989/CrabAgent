// @vitest-environment jsdom
import "fake-indexeddb/auto";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_COLORS, parseThemes, ThemeProvider, useTheme, validImage } from "./theme";

describe("custom themes", () => {
  let container: HTMLDivElement;
  let root: Root;
  let change: ((event: MediaQueryListEvent) => void) | undefined;
  let matches = false;
  beforeEach(() => {
    const store = new Map<string, string>();
    Object.defineProperty(globalThis, "localStorage", { configurable: true, value: { getItem: (key: string) => store.get(key) ?? null, setItem: (key: string, value: string) => store.set(key, value) } });
    Object.defineProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT", { value: true, configurable: true });
    Object.defineProperty(window, "matchMedia", { configurable: true, value: () => ({ get matches() { return matches; }, addEventListener: (_: string, fn: typeof change) => { change = fn; }, removeEventListener: vi.fn() }) });
    container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  });
  afterEach(() => { act(() => root.unmount()); container.remove(); document.documentElement.removeAttribute("style"); matches = false; });
  it("validates stored themes and image sources", () => {
    expect(parseThemes("broken")).toEqual([]);
    expect(parseThemes(JSON.stringify([{ id: "1", name: "test", colors: DEFAULT_COLORS.dark, backgroundImage: "javascript:alert(1)" }]))).toEqual([]);
    expect(validImage("https://example.com/a.png")).toBe(true);
    expect(validImage("data:image/svg+xml;base64,PHN2Zz4=")).toBe(false);
  });
  it("migrates legacy themes and rejects incomplete palettes", () => {
    const old = { id: "old", name: "Old", backgroundImage: "", colors: { brand: "#123456", accent: "#abcdef", background: "#111111", text: "#eeeeee" } };
    const [migrated] = parseThemes(JSON.stringify([old]));
    expect(migrated.colors.light.brand).toBe("#123456");
    expect(migrated.colors.dark["bg-primary"]).toBe("#111111");
    expect(migrated.colors.light["bg-secondary"]).toBe(DEFAULT_COLORS.light["bg-secondary"]);
    expect(parseThemes(JSON.stringify([{ ...old, colors: { light: DEFAULT_COLORS.light, dark: {} } }]))).toEqual([]);
  });
  it("tracks system changes and persists, applies and deletes themes", async () => {
    let value!: ReturnType<typeof useTheme>;
    function Probe() { value = useTheme(); return null; }
    act(() => root.render(<ThemeProvider><Probe /></ThemeProvider>));
    expect(value.mode).toBe("system"); expect(value.theme).toBe("dark");
    matches = true; act(() => change?.({ matches: true } as MediaQueryListEvent));
    expect(value.theme).toBe("light");
    await act(async () => value.saveTheme({ id: "one", name: "Ocean", colors: { light: { ...DEFAULT_COLORS.light, brand: "#123456" }, dark: { ...DEFAULT_COLORS.dark } }, backgroundImage: "https://example.com/a.png" }));
    expect(document.documentElement.style.getPropertyValue("--brand")).toBe("#123456");
    act(() => value.setMode("dark"));
    expect(document.documentElement.style.getPropertyValue("--brand")).toBe(DEFAULT_COLORS.dark.brand);
    expect(localStorage.getItem("crabagent.activeTheme")).toBe("one");
    await act(async () => value.deleteTheme("one"));
    expect(value.activeId).toBe(""); expect(document.documentElement.style.getPropertyValue("--brand")).toBe("");
    act(() => value.setMode("dark")); expect(localStorage.getItem("crabagent.theme")).toBe("dark");
  });
});

describe("image storage", () => {
  it("stores, replaces and removes binary images", async () => {
    const { putThemeImage, getThemeImage, deleteThemeImage } = await import("./theme-images");
    const originalClone = globalThis.structuredClone;
    globalThis.structuredClone = ((value: unknown) => value) as typeof structuredClone;
    const image = new Blob([new Uint8Array(10 * 1024 * 1024)], { type: "image/png" });
    await putThemeImage("test-image", image);
    expect((await getThemeImage("test-image"))?.size).toBe(image.size);
    await putThemeImage("test-image", new Blob(["new"], { type: "image/png" }) as unknown as Blob);
    expect((await getThemeImage("test-image"))?.size).toBe(3);
    await deleteThemeImage("test-image");
    expect(await getThemeImage("test-image")).toBeUndefined();
    globalThis.structuredClone = originalClone;
  });
  it("rejects when IndexedDB cannot be opened", async () => {
    const { putThemeImage } = await import("./theme-images");
    const spy = vi.spyOn(indexedDB, "open").mockImplementation(() => { throw new Error("denied"); });
    await expect(putThemeImage("failure", new Blob())).rejects.toThrow("denied");
    spy.mockRestore();
  });
});

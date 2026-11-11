// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { LanguageSwitcher } from "./NavBar";

const mocks = vi.hoisted(() => ({ patch: vi.fn(), post: vi.fn(), update: vi.fn(), error: vi.fn(), change: vi.fn() }));
vi.mock("../i18n", () => ({ SUPPORTED_LANGUAGES: [{ code: "en" }, { code: "zh-CN" }] }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en", changeLanguage: mocks.change } }) }));
vi.mock("../lib/theme", () => ({ useTheme: () => ({ theme: "light", toggleTheme: vi.fn() }) }));
vi.mock("sonner", () => ({ toast: { error: mocks.error } }));
vi.mock("../api/client", () => ({ api: { patch: mocks.patch, post: mocks.post } }));
vi.mock("../api/settings", () => ({ updateSettings: mocks.update }));
vi.mock("./ui", () => ({ Modal: ({ open, footer }: { open: boolean; footer: React.ReactNode }) => open ? <div>{footer}</div> : null, Button: ({ children, onClick }: { children: React.ReactNode; onClick: () => void }) => <button onClick={onClick}>{children}</button> }));

it("reports partial synchronization failures while attempting all updates", async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal("localStorage", { setItem: vi.fn() });
  mocks.update.mockRejectedValueOnce(new Error("offline"));
  mocks.patch.mockResolvedValueOnce({}); mocks.post.mockResolvedValueOnce({});
  const element = document.createElement("div"); document.body.append(element);
  const root = createRoot(element);
  await act(async () => root.render(<LanguageSwitcher sessionId="s1" />));
  await act(async () => element.querySelector<HTMLButtonElement>('[aria-label="language.title"]')!.click());
  const confirm = [...element.querySelectorAll("button")].find((button) => button.textContent === "language.switchConfirm")!;
  await act(async () => confirm.click());
  expect(mocks.patch).toHaveBeenCalled(); expect(mocks.post).toHaveBeenCalled();
  expect(mocks.error).toHaveBeenCalledWith("language.syncFailed");
  await act(async () => root.unmount()); element.remove();
});

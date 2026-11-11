// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import LoginPage from "./LoginPage";
const mocks = vi.hoisted(() => ({ login: vi.fn(), register: vi.fn(), patch: vi.fn(), setToken: vi.fn(), clearToken: vi.fn(), language: { language: "en", changeLanguage: vi.fn() } }));
vi.mock("../api/client", () => ({ api: { patch: mocks.patch, setToken: mocks.setToken, clearToken: mocks.clearToken } }));
vi.mock("../api/auth", () => ({ login: mocks.login, register: mocks.register }));
vi.mock("../i18n", () => ({ SUPPORTED_LANGUAGES: [{ code: "en", label: "English" }, { code: "zh-CN", label: "简体中文" }] }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: mocks.language }) }));
it.each([false, true])("syncs selected login language before entering (failure: %s)", async (fail) => {
 vi.clearAllMocks(); vi.stubGlobal("localStorage", { setItem: vi.fn() }); mocks.language.language = "en";
 mocks.language.changeLanguage.mockImplementation((lang: string) => { mocks.language.language = lang; });
 mocks.login.mockResolvedValue({ access_token: "token" }); mocks.patch.mockResolvedValue({});
 if (fail) mocks.patch.mockRejectedValueOnce(new Error("offline"));
 (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
 const element = document.createElement("div"); document.body.append(element); const root = createRoot(element); const onLogin = vi.fn();
 await act(async () => root.render(<LoginPage onLogin={onLogin} />));
 await act(async () => [...element.querySelectorAll("button")].find((b) => b.textContent === "简体中文")!.click());
 await act(async () => element.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
 expect(mocks.setToken).toHaveBeenCalledWith("token"); expect(mocks.patch).toHaveBeenCalledWith("/auth/user", { locale: "zh-CN" });
 expect(mocks.setToken.mock.invocationCallOrder[0]).toBeLessThan(mocks.patch.mock.invocationCallOrder[0]);
 if (fail) { expect(onLogin).not.toHaveBeenCalled(); expect(mocks.clearToken).toHaveBeenCalled(); expect(element.textContent).toContain("language.syncFailed"); }
 else { expect(onLogin).toHaveBeenCalledOnce(); expect(mocks.patch.mock.invocationCallOrder[0]).toBeLessThan(onLogin.mock.invocationCallOrder[0]); }
 await act(async () => root.unmount()); element.remove();
});

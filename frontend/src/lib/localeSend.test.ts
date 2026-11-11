import { beforeEach, expect, it, vi } from "vitest";
import { sendWithLocale } from "./localeSend";
const mocks = vi.hoisted(() => ({ patch: vi.fn(), post: vi.fn() }));
vi.mock("../api/client", () => ({ api: mocks }));
const draft = { pendingText: "hello", pendingImages: ["data:image/png;base64,abc"], pendingFiles: [{ name: "a.txt", path: "/tmp/a.txt", size: 42 }] };
beforeEach(() => vi.resetAllMocks());
it("updates locale before reset and sends the complete draft", async () => {
 const order: string[] = [];
 mocks.patch.mockImplementation(async () => { order.push("patch"); });
 mocks.post.mockImplementation(async () => { order.push("reset"); });
 const send = vi.fn(async () => { order.push("send"); });
 await sendWithLocale("s1", "zh-CN", draft, send, () => order.push("ready"));
 expect(mocks.patch).toHaveBeenCalledWith("/auth/user", { locale: "zh-CN" });
 expect(mocks.post).toHaveBeenCalledWith("/sessions/s1/reset-system-prompt", {});
 expect(order).toEqual(["patch", "reset", "ready", "send"]); expect(send).toHaveBeenCalledWith(draft);
});
it.each(["patch", "post"] as const)("does not clear or send the draft if %s fails", async (failed) => {
 mocks[failed].mockRejectedValueOnce(new Error("offline")); const ready = vi.fn(); const send = vi.fn();
 await expect(sendWithLocale("s1", "zh-CN", draft, send, ready)).rejects.toThrow("offline");
 expect(ready).not.toHaveBeenCalled(); expect(send).not.toHaveBeenCalled();
 if (failed === "patch") expect(mocks.post).not.toHaveBeenCalled();
 expect(draft.pendingImages).toHaveLength(1); expect(draft.pendingFiles).toHaveLength(1);
});

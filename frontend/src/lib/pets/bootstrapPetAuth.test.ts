import { describe, expect, it, vi } from "vitest";
import { bootstrapPetAuth } from "./bootstrapPetAuth";

describe("bootstrapPetAuth", () => {
  it("sets the API token before allowing consumers to mount", async () => {
    const events: string[] = [];
    let resolveToken!: (token: string) => void;
    const token = new Promise<string>((resolve) => { resolveToken = resolve; });
    const initialize = bootstrapPetAuth(
      { setToken: (value) => { events.push(value); } },
      () => token,
    ).then(() => { events.push("mount"); });
    expect(events).toEqual([]);
    resolveToken("test-token");
    await initialize;
    expect(events).toEqual(["test-token", "mount"]);
  });

  it("leaves browser sessions unchanged when no bridge is present", async () => {
    const setToken = vi.fn();
    await bootstrapPetAuth({ setToken });
    expect(setToken).not.toHaveBeenCalled();
  });

  it("does not mount authenticated consumers when the bridge has no token", async () => {
    const setToken = vi.fn();
    const mount = vi.fn();
    await expect(bootstrapPetAuth({ setToken }, async () => null).then(mount))
      .rejects.toThrow("Pet authentication is not ready");
    expect(setToken).not.toHaveBeenCalled();
    expect(mount).not.toHaveBeenCalled();
  });

  it("propagates bridge failures without changing the stored session", async () => {
    const setToken = vi.fn();
    await expect(bootstrapPetAuth({ setToken }, async () => { throw new Error("bridge unavailable"); }))
      .rejects.toThrow("bridge unavailable");
    expect(setToken).not.toHaveBeenCalled();
  });
});

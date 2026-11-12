import page from "./ChatPage.tsx?raw";

import { describe, expect, it } from "vitest";


describe("chat theme background", () => {
  it("uses the custom image on the chat page with a solid fallback", () => {
    expect(page).toContain("chat-page-background relative flex h-full overflow-hidden bg-[var(--bg-primary)]");
  });

  it("does not obscure the background in work-mode chat", () => {
    expect(page).toContain('overflow-hidden border-r border-[var(--border)] flex-col md:flex');
  });
});

import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import ChatInput from "./ChatInput";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

describe("chat composer responsive layout", () => {
  const props = { replaying: false, onSend: () => {}, onAbort: () => {}, onFileUpload: () => {}, onFilePaste: () => {}, onDelegateOpen: () => {} };
  it("keeps the input shrinkable and exposes mobile actions", () => {
    const html = renderToStaticMarkup(<ChatInput {...props} sending={false} showDelegate onGoalOpen={() => {}} />);
    expect(html).toContain("order-first basis-full sm:order-none sm:basis-auto sm:flex-1");
    expect(html).toContain('aria-label="chat.delegate"');
    expect(html).toContain('aria-label="chat.attachFile"');
    expect(html).toContain('aria-label="common.send"');
  });
  it("exposes stop while sending", () => {
    const html = renderToStaticMarkup(<ChatInput {...props} sending />);
    expect(html).toContain('aria-label="common.stop"');
  });
});

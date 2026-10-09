import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { RichMarkdown } from "./RichMarkdown";
import { markdownImageUrl } from "./markdownImageUrl";

vi.mock("../../api/client", () => ({ api: {} }));

afterEach(() => vi.unstubAllGlobals());
function authenticate() {
  vi.stubGlobal("localStorage", { getItem: () => "test-token" });
}
describe("Markdown workspace images", () => {
  it("uses the authenticated file API for normal and streaming Markdown", () => {
    authenticate();
    for (const isStreaming of [false, true]) {
      const html = renderToStaticMarkup(<RichMarkdown isStreaming={isStreaming}>{"![preview](previews/workspace/desktop.png)"}</RichMarkdown>);
      expect(html).toContain("/api/files/image?path=previews%2Fworkspace%2Fdesktop.png&amp;absolute=false&amp;token=test-token");
    }
  });
  it("normalizes relative and encoded paths and supports absolute file paths", () => {
    authenticate();
    const url = new URL(markdownImageUrl("./previews/folder/../my%20image.png"), "https://app.invalid");
    expect(url.searchParams.get("path")).toBe("previews/my image.png");
    expect(url.searchParams.get("token")).toBe("test-token");
    expect(new URL(markdownImageUrl("/Users/me/image.png"), "https://app.invalid").searchParams.get("absolute")).toBe("true");
  });
  it("does not add credentials to remote or API images", () => {
    for (const value of ["https://example.com/a.png", "http://example.com/a.png", "//example.com/a.png", "/api/files/image?path=a.png&token=existing"]) {
      expect(markdownImageUrl(value)).toBe(value);
    }
  });
  it("rejects unsafe schemes, escaping paths and malformed encodings", () => {
    for (const value of ["javascript:alert(1)", "file:///tmp/a.png", "../a.png", "%2e%2e/a.png", "%zz", "a%00.png", "%2f%2fevil.invalid/a.png"]) {
      expect(markdownImageUrl(value)).toBe("");
    }
  });
});

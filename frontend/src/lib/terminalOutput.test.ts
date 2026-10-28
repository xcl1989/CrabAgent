import { describe, expect, it } from "vitest";
import { terminalOutput } from "./terminalOutput";

describe("terminal output", () => {
  it("hides ANSI colors, clear-line and cursor visibility sequences", () => {
    expect(terminalOutput("\x1b[?25l\r\x1b[2K\x1b[35m48%\x1b[0m\r\x1b[2K\x1b[35m100%\x1b[0m\x1b[?25h\nDone\n"))
      .toBe("100%\nDone\n");
  });
  it("keeps ordinary newlines, CRLF and blank lines", () => {
    expect(terminalOutput("first\r\n\r\nlast\n")).toBe("first\n\nlast\n");
  });
  it("implements carriage return overwrite rather than appending lines", () => {
    expect(terminalOutput("abcdef\rXY")).toBe("XYcdef");
    expect(terminalOutput("abcdef\rXY\x1b[K")).toBe("XY");
  });
  it("handles backspace, tabs, cursor movement and multiline progress", () => {
    expect(terminalOutput("abc\bX\tend")).toBe("abX     end");
    expect(terminalOutput("old\nsecond\x1b[1A\r\x1b[2Knew")).toBe("new\nsecond");
  });
  it("does not expose split escape sequences", () => {
    const prefix = "output\x1b[3";
    expect(terminalOutput(prefix)).toBe("output");
    expect(terminalOutput(prefix + "1mred\x1b[0m")).toBe("outputred");
  });
  it("strips OSC links and titles without interpreting HTML", () => {
    expect(terminalOutput("\x1b]0;title\x07\x1b]8;;https://example.com\x1b\\label\x1b]8;;\x1b\\<b>"))
      .toBe("label<b>");
  });
  it("preserves Unicode and normal bracketed output", () => {
    expect(terminalOutput("[stderr]\n中文🙂 [91m literal")).toBe("[stderr]\n中文🙂 [91m literal");
  });
});

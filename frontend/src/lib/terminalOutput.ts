/** Render terminal controls as plain text, never HTML or executable links. */
export function terminalOutput(raw: string): string {
  const lines: string[][] = [[]];
  let row = 0;
  let column = 0;
  const line = () => (lines[row] ??= []);
  const moveRow = (value: number) => {
    row = Math.max(0, Math.min(value, lines.length + 1000));
    while (lines.length <= row) lines.push([]);
  };
  for (let i = 0; i < raw.length;) {
    const c = raw[i];
    // CSI includes colors, erase-line, and cursor movement used by progress UIs.
    const csiStart = raw.startsWith("\x1b[", i) ? 2 : c === "\x9b" ? 1 : 0;
    if (csiStart) {
      const match = raw.slice(i + csiStart).match(/^([0-?]*)([ -/]*)([@-~])/);
      if (!match) break; // An escape sequence split across SSE chunks is not visible yet.
      const params = match[1].split(";").map((v) => Number(v) || 0);
      const amount = Math.min(params[0] || 1, 10000);
      switch (match[3]) {
        case "K":
          if (params[0] === 2) lines[row] = [];
          else if (params[0] === 1) {
            for (let n = 0; n <= Math.min(column, 10000); n++) line()[n] = " ";
          } else line().splice(column);
          break;
        case "A": moveRow(row - amount); break;
        case "B": moveRow(row + amount); break;
        case "C": column = Math.min(10000, column + amount); break;
        case "D": column = Math.max(0, column - amount); break;
        case "G": column = amount - 1; break;
        case "H": case "f":
          moveRow((params[0] || 1) - 1);
          column = Math.min(10000, (params[1] || 1) - 1);
          break;
        case "J":
          if (params[0] === 2 || params[0] === 3) {
            lines.splice(0, lines.length, []);
            row = 0;
            column = 0;
          }
          break;
      }
      i += csiStart + match[0].length;
      continue;
    }
    if (raw.startsWith("\x1b]", i)) {
      // OSC titles and hyperlinks: discard metadata but retain the link label.
      const end = raw.slice(i + 2).search(/\x07|\x1b\\/);
      if (end < 0) break;
      const pos = i + 2 + end;
      i = pos + (raw[pos] === "\x07" ? 1 : 2);
      continue;
    }
    if (c === "\x1b") {
      if (i + 1 >= raw.length) break;
      i += 2;
      continue;
    }
    if (c === "\r") column = 0;
    else if (c === "\n") { moveRow(row + 1); column = 0; }
    else if (c === "\b") column = Math.max(0, column - 1);
    else if (c === "\t") {
      const end = Math.min(10000, column + 8 - column % 8);
      while (column < end) line()[column++] = " ";
    } else if (c >= " " && c !== "\x7f") {
      const char = String.fromCodePoint(raw.codePointAt(i)!);
      while (line().length < column) line().push(" ");
      line()[column++] = char;
      i += char.length;
      continue;
    }
    i++;
  }
  return lines.map((value) => value.join("")).join("\n");
}

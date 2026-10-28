export function getToolSummary(content: string): { name: string; summary: string } {
  try {
    const data = JSON.parse(content);
    const name = data.name || "unknown";
    const args = data.arguments || {};
    // "summary" is the current display-metadata key; "_summary" is kept for
    // messages recorded by older sessions.
    const meta = [args.summary, args._summary].find(
      (value) => typeof value === "string" && value.trim(),
    );
    if (typeof meta === "string") {
      return { name, summary: meta.replace(/\s+/g, " ").trim().slice(0, 40) };
    }
    const firstKey = Object.keys(args).find((key) => key !== "summary" && key !== "_summary");
    const val = firstKey ? args[firstKey] : undefined;
    const summary = typeof val === "string" ? val : JSON.stringify(val);
    return { name, summary: (summary || "").slice(0, 40) };
  } catch {
    return { name: "unknown", summary: content.slice(0, 40) };
  }
}

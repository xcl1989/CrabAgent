export function getToolSummary(content: string): { name: string; summary: string } {
  try {
    const data = JSON.parse(content);
    const name = data.name || "unknown";
    const args = data.arguments || {};
    if (typeof args._summary === "string" && args._summary.trim()) {
      return { name, summary: args._summary.replace(/\s+/g, " ").trim().slice(0, 40) };
    }
    const firstKey = Object.keys(args).find((key) => key !== "_summary");
    const val = firstKey ? args[firstKey] : undefined;
    const summary = typeof val === "string" ? val : JSON.stringify(val);
    return { name, summary: (summary || "").slice(0, 40) };
  } catch {
    return { name: "unknown", summary: content.slice(0, 40) };
  }
}

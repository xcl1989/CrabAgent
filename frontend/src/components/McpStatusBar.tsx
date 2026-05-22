import { useState } from "react";
import { McpServerStatus, McpTool } from "../api/mcpServers";

interface Props {
  status: McpServerStatus[];
}

function StatusDot({ status }: { status: string }) {
  const color =
    status === "connected" ? "#34d399" : status === "connecting" ? "#fbbf24" : status === "error" ? "#f87171" : "var(--text-secondary)";
  return (
    <span
      style={{
        display: "inline-block",
        width: 6,
        height: 6,
        borderRadius: "50%",
        background: color,
        marginRight: 4,
        flexShrink: 0,
      }}
    />
  );
}

function ToolList({ tools }: { tools: McpTool[] }) {
  if (!tools.length) return null;
  return (
    <div className="mt-1.5 ml-3 pl-2" style={{ borderLeft: "1px solid var(--border)" }}>
      {tools.map((t, i) => (
        <div key={i} className="text-xs py-0.5" style={{ color: "var(--text-secondary)" }}>
          <span style={{ color: "#67e8f9", fontFamily: "monospace" }}>{t.name}</span>
          {t.description && <span> - {t.description.slice(0, 60)}</span>}
        </div>
      ))}
    </div>
  );
}

export default function McpStatusBar({ status }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (!status.length) return null;

  return (
    <div
      className="px-4 py-1.5 flex items-center gap-3 overflow-x-auto"
      style={{ borderBottom: "1px solid var(--border)", background: "var(--bg-secondary)" }}
    >
      <span style={{ color: "#a78bfa", fontSize: "12px", flexShrink: 0 }}>&#x1f50c;</span>
      {status.map((s) => (
        <div key={s.name} className="flex-shrink-0">
          <button
            onClick={() => setExpanded(expanded === s.name ? null : s.name)}
            className="flex items-center gap-1 text-xs px-2 py-0.5 rounded cursor-pointer"
            style={{
              background: expanded === s.name ? "var(--bg-tertiary)" : "transparent",
              border: "1px solid transparent",
              color: "var(--text-secondary)",
              fontFamily: "'SF Mono', 'Fira Code', monospace",
            }}
            title={s.error || s.status}
          >
            <StatusDot status={s.status} />
            <span style={{ color: s.status === "connected" ? "var(--text-primary)" : "var(--text-secondary)" }}>
              {s.display_name || s.name}
            </span>
            {s.status === "connected" && s.tool_count > 0 && (
              <span style={{ color: "var(--text-secondary)", fontSize: "10px" }}>({s.tool_count})</span>
            )}
            {s.status === "error" && (
              <span style={{ color: "#f87171", fontSize: "10px" }}>!</span>
            )}
          </button>
          {expanded === s.name && <ToolList tools={s.tools} />}
        </div>
      ))}
    </div>
  );
}

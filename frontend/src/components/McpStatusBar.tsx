import { useState } from "react";
import { Plug } from "lucide-react";
import { McpServerStatus, McpTool } from "../api/mcpServers";
import { useThemeColors } from "../lib/theme-colors";

interface Props {
  status: McpServerStatus[];
}

function StatusDot({
  status,
  colors,
}: {
  status: string;
  colors: ReturnType<typeof useThemeColors>;
}) {
  const color =
    status === "connected"
      ? colors.success
      : status === "connecting"
        ? colors.warning
        : status === "error"
          ? colors.danger
          : colors.textTertiary;
  return (
    <span
      className="inline-block w-1.5 h-1.5 rounded-full mr-1 shrink-0"
      style={{ background: color }}
    />
  );
}

function ToolList({
  tools,
  colors,
}: {
  tools: McpTool[];
  colors: ReturnType<typeof useThemeColors>;
}) {
  if (!tools.length) return null;
  return (
    <div
      className="mt-1.5 ml-3 pl-2"
      style={{ borderLeft: "1px solid var(--border)" }}
    >
      {tools.map((t, i) => (
        <div
          key={i}
          className="text-xs py-0.5 text-[var(--text-secondary)]"
        >
          <span style={{ color: colors.accent }} className="font-mono">
            {t.name}
          </span>
          {t.description && (
            <span> - {t.description.slice(0, 60)}</span>
          )}
        </div>
      ))}
    </div>
  );
}

export default function McpStatusBar({ status }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const colors = useThemeColors();

  if (!status.length) return null;

  return (
    <div className="px-4 py-1.5 flex items-center gap-3 overflow-x-auto border-b border-[var(--border)] bg-[var(--bg-secondary)]">
      <Plug size={12} className="shrink-0" style={{ color: colors.accent2 }} />
      {status.map((s) => (
        <div key={s.name} className="shrink-0">
          <button
            onClick={() =>
              setExpanded(expanded === s.name ? null : s.name)
            }
            className="flex items-center gap-1 text-xs px-2 py-0.5 rounded cursor-pointer font-mono border border-transparent transition-colors"
            style={{
              background:
                expanded === s.name
                  ? "var(--bg-tertiary)"
                  : "transparent",
              color: "var(--text-secondary)",
            }}
            title={s.error || s.status}
          >
            <StatusDot status={s.status} colors={colors} />
            <span
              style={{
                color:
                  s.status === "connected"
                    ? "var(--text-primary)"
                    : "var(--text-secondary)",
              }}
            >
              {s.display_name || s.name}
            </span>
            {s.status === "connected" && s.tool_count > 0 && (
              <span className="text-[10px] text-[var(--text-secondary)]">
                ({s.tool_count})
              </span>
            )}
            {s.status === "error" && (
              <span
                className="text-[10px]"
                style={{ color: colors.danger }}
              >
                !
              </span>
            )}
          </button>
          {expanded === s.name && <ToolList tools={s.tools} colors={colors} />}
        </div>
      ))}
    </div>
  );
}

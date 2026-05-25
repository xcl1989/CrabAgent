import { useState } from "react";
import { Session } from "../api/sessions";
import { formatDate } from "../api/time";

interface Props {
  sessions: Session[];
  activeId: string | null;
  onSelect: (session: Session) => void;
  onNew: () => void;
  onDelete: (sessionId: string) => void;
  onOpenProviders: () => void;
  onOpenMcpServers: () => void;
  onOpenScheduledTasks: () => void;
  onOpenAgentTeam: () => void;
}

export default function SessionList({ sessions, activeId, onSelect, onNew, onDelete, onOpenProviders, onOpenMcpServers, onOpenScheduledTasks, onOpenAgentTeam }: Props) {
  const [collapsed, setCollapsed] = useState(false);

  if (collapsed) {
    return (
      <div className="flex flex-col items-center py-3 gap-3 border-r" style={{ width: 48, background: "var(--bg-secondary)", borderRight: "1px solid var(--border)" }}>
        <button onClick={() => setCollapsed(false)} className="text-sm px-2 py-1 rounded" style={{ color: "var(--text-secondary)" }} title="Expand sessions">
          ☰
        </button>
        <div className="flex-1" />
        <button onClick={onOpenMcpServers} className="text-xs" style={{ color: "#a78bfa" }} title="MCP Servers">
          &#x1f50c;
        </button>
        <button onClick={onOpenScheduledTasks} className="text-xs" style={{ color: "#fbbf24" }} title="Scheduled Tasks">
          🕐
        </button>
        <button onClick={onOpenAgentTeam} className="text-xs" style={{ color: "#8b5cf6" }} title="Agent Team">
          🤖
        </button>
        <button onClick={onOpenProviders} className="text-xs" style={{ color: "var(--text-secondary)" }} title="Providers">
          ⚙
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col border-r" style={{ width: 256, background: "var(--bg-secondary)", borderRight: "1px solid var(--border)" }}>
      <div className="p-3 flex items-center justify-between border-b" style={{ borderBottom: "1px solid var(--border)" }}>
        <span className="text-sm font-semibold">Sessions</span>
        <div className="flex items-center gap-1">
          <button onClick={onNew} className="text-xs px-2 py-1 rounded" style={{ background: "var(--accent)", color: "#fff" }}>
            + New
          </button>
          <button onClick={() => setCollapsed(true)} className="text-xs px-1 py-1 rounded" style={{ color: "var(--text-secondary)" }} title="Collapse">
            ◀
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {sessions.map((s) => (
          <div
            key={s.session_id}
            onClick={() => onSelect(s)}
            className="px-3 py-2 cursor-pointer text-sm group flex items-center justify-between"
            style={{
              background: activeId === s.session_id ? "var(--bg-tertiary)" : "transparent",
              borderBottom: "1px solid var(--border)",
            }}
          >
            <div className="min-w-0 flex-1">
              <div className="truncate flex items-center gap-1.5" style={{ color: "var(--text-primary)" }}>
                {s.title || "(untitled)"}
                {s.active_branch && s.active_branch !== "main" && (
                  <span className="text-[10px] px-1 py-0 rounded flex-shrink-0" style={{ background: "var(--bg-tertiary)", color: "#fbbf24" }}>
                    ⎇ {s.active_branch}
                  </span>
                )}
              </div>
              <div className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
                {formatDate(s.updated_at)}
              </div>
            </div>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete(s.session_id);
              }}
              className="opacity-0 group-hover:opacity-100 text-xs ml-2 px-1"
              style={{ color: "var(--danger)" }}
            >
              x
            </button>
          </div>
        ))}
        {sessions.length === 0 && (
          <div className="p-4 text-xs text-center" style={{ color: "var(--text-secondary)" }}>
            No sessions yet
          </div>
        )}
      </div>

      <div className="p-2 flex gap-1.5 border-t" style={{ borderTop: "1px solid var(--border)" }}>
        <button
          onClick={onOpenMcpServers}
          className="flex-1 text-[10px] py-1.5 rounded font-medium tracking-wide"
          style={{ background: "#2d1f5e", color: "#a78bfa" }}
        >
          MCP
        </button>
        <button
          onClick={onOpenScheduledTasks}
          className="flex-1 text-[10px] py-1.5 rounded font-medium tracking-wide"
          style={{ background: "#2d1f5e", color: "#fbbf24" }}
        >
          Tasks
        </button>
        <button
          onClick={onOpenAgentTeam}
          className="flex-1 text-[10px] py-1.5 rounded font-medium tracking-wide"
          style={{ background: "#4c1d95", color: "#a78bfa" }}
        >
          Team
        </button>
        <button
          onClick={onOpenProviders}
          className="flex-1 text-[10px] py-1.5 rounded font-medium tracking-wide"
          style={{ background: "var(--bg-tertiary)", color: "var(--text-secondary)" }}
        >
          Providers
        </button>
      </div>
    </div>
  );
}

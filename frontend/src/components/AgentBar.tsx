import { useState, useEffect } from "react";
import { AgentProfile, listAgentProfiles } from "../api/agents";
import { Tooltip } from "./ui";
import { cn } from "../lib/cn";

interface Props {
  onAgentClick: (agent: AgentProfile) => void;
}

const AGENT_COLOR: Record<string, string> = {
  researcher: "text-[var(--agent-researcher)] border-[var(--agent-researcher)]/30 hover:bg-[var(--agent-researcher-bg)]",
  analyst: "text-[var(--agent-analyst)] border-[var(--agent-analyst)]/30 hover:bg-[var(--agent-analyst-bg)]",
  coder: "text-[var(--agent-coder)] border-[var(--agent-coder)]/30 hover:bg-[var(--agent-coder-bg)]",
  writer: "text-[var(--agent-writer)] border-[var(--agent-writer)]/30 hover:bg-[var(--agent-writer-bg)]",
};

export function AgentBar({ onAgentClick }: Props) {
  const [agents, setAgents] = useState<AgentProfile[]>([]);

  useEffect(() => {
    listAgentProfiles()
      .then((list) => setAgents(list.filter((a) => a.enabled)))
      .catch(() => {});
  }, []);

  if (agents.length === 0) return null;

  return (
    <div className="flex items-center gap-1.5 overflow-x-auto pb-1.5 mb-1.5 scrollbar-none">
      {agents.map((a) => {
        const colorClass =
          AGENT_COLOR[a.name] ||
          "text-[var(--text-secondary)] border-[var(--border)] hover:bg-[var(--bg-tertiary)]";
        return (
          <Tooltip
            key={a.id}
            content={
              <span>
                <span className="text-[var(--text-primary)] font-medium">
                  @{a.name}
                </span>
                <span className="text-[var(--text-tertiary)]"> · {a.role}</span>
              </span>
            }
            side="bottom"
          >
            <button
              onClick={() => onAgentClick(a)}
              className={cn(
                "flex items-center gap-1 h-7 px-2 rounded-full text-[11px] font-medium shrink-0",
                "bg-[var(--bg-secondary)] border transition-all",
                "hover:scale-105 active:scale-95",
                colorClass,
              )}
            >
              <span className="text-xs">{a.icon || "🤖"}</span>
              <span className="truncate max-w-[80px]">
                {a.display_name.split(" ")[0]}
              </span>
            </button>
          </Tooltip>
        );
      })}
    </div>
  );
}

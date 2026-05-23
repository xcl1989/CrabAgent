import { useState, useEffect } from "react";
import { AgentProfile, listAgentProfiles } from "../api/agents";

interface Props {
  onAgentClick: (agent: AgentProfile) => void;
}

export function AgentBar({ onAgentClick }: Props) {
  const [agents, setAgents] = useState<AgentProfile[]>([]);

  useEffect(() => {
    listAgentProfiles().then((list) => setAgents(list.filter((a) => a.enabled))).catch(() => {});
  }, []);

  if (agents.length === 0) return null;

  return (
    <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-none">
      {agents.map((a) => (
        <button
          key={a.id}
          onClick={() => onAgentClick(a)}
          className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] shrink-0 transition-all hover:scale-105 active:scale-95"
          style={{
            background: "var(--bg-tertiary)",
            border: "1px solid var(--border)",
            color: "var(--text-secondary)",
          }}
          title={`Click to @${a.name} — ${a.role}`}
        >
          <span className="text-xs">{a.icon || "🤖"}</span>
          <span className="truncate max-w-[60px]">{a.display_name.split(" ")[0]}</span>
        </button>
      ))}
    </div>
  );
}

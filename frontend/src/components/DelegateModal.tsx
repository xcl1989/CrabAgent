import { useState, useEffect } from "react";
import { AgentProfile, listAgentProfiles } from "../api/agents";

interface Props {
  onClose: () => void;
  onDelegate: (tasks: { agent_name: string; task: string }[]) => void;
}

export function DelegateModal({ onClose, onDelegate }: Props) {
  const [agents, setAgents] = useState<AgentProfile[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [task, setTask] = useState("");
  const [customTasks, setCustomTasks] = useState<Record<string, string>>({});

  useEffect(() => {
    listAgentProfiles().then((list) => setAgents(list.filter((a) => a.enabled))).catch(() => {});
  }, []);

  const toggle = (name: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const handleDelegate = () => {
    if (selected.size === 0 || !task.trim()) return;
    const tasks = Array.from(selected).map((name) => ({
      agent_name: name,
      task: customTasks[name]?.trim() || task.trim(),
    }));
    onDelegate(tasks);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "var(--overlay)" }}>
      <div className="w-full max-w-md rounded-xl overflow-hidden" style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", boxShadow: "0 25px 60px rgba(0,0,0,0.5), var(--glow-accent-2)" }}>
        <div className="flex items-center justify-between px-5 py-3.5" style={{ borderBottom: "1px solid var(--border)", background: "var(--bg-tertiary)" }}>
          <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Delegate to Team</h3>
          <button onClick={onClose} className="text-sm opacity-60 hover:opacity-100 transition-opacity" style={{ color: "var(--text-secondary)" }}>✕</button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--text-secondary)" }}>
              Select Agents
            </label>
            <div className="flex flex-wrap gap-2">
              {agents.map((a) => (
                <button
                  key={a.id}
                  onClick={() => toggle(a.name)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs transition-all"
                  style={{
                    background: selected.has(a.name) ? "var(--accent-2)" : "var(--bg-tertiary)",
                    border: `1px solid ${selected.has(a.name) ? "var(--accent-2)" : "var(--border)"}`,
                    color: selected.has(a.name) ? "var(--text-on-accent)" : "var(--text-secondary)",
                    boxShadow: selected.has(a.name) ? "var(--glow-accent-2)" : "none",
                  }}
                >
                  <span>{a.icon || "🤖"}</span>
                  <span>{a.display_name}</span>
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider mb-1" style={{ color: "var(--text-secondary)" }}>
              Task Description
            </label>
            <textarea
              value={task}
              onChange={(e) => setTask(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 rounded-lg text-xs outline-none resize-none"
              style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              placeholder="Describe what you want the agent(s) to do..."
              autoFocus
            />
          </div>

          {selected.size > 1 && (
            <div>
              <label className="block text-[10px] font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--text-secondary)" }}>
                Custom Tasks (optional — override the task for specific agents)
              </label>
              {Array.from(selected).map((name) => {
                const agent = agents.find((a) => a.name === name);
                return (
                  <div key={name} className="flex items-center gap-2 mb-2">
                    <span className="text-xs shrink-0">{agent?.icon || "🤖"}</span>
                    <span className="text-[10px] shrink-0 w-20 truncate" style={{ color: "var(--text-secondary)" }}>{name}</span>
                    <input
                      value={customTasks[name] || ""}
                      onChange={(e) => setCustomTasks({ ...customTasks, [name]: e.target.value })}
                      className="flex-1 px-2 py-1 rounded text-[10px] outline-none"
                      style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                      placeholder="Same as above if empty"
                    />
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex gap-2 px-5 py-3" style={{ borderTop: "1px solid var(--border)" }}>
          <button
            onClick={handleDelegate}
            disabled={selected.size === 0 || !task.trim()}
            className="flex-1 py-2 rounded-lg text-xs font-medium text-white disabled:opacity-40 transition-opacity"
             style={{ background: "var(--accent-2)" }}
          >
            Delegate to {selected.size} agent{selected.size !== 1 ? "s" : ""}
          </button>
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-xs transition-opacity"
            style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)" }}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

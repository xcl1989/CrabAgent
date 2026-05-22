import { useState, useEffect } from "react";
import { AgentProfile, listAgentProfiles, updateAgentProfile } from "../api/agents";

interface Props {
  onClose: () => void;
}

export function AgentTeamPanel({ onClose }: Props) {
  const [agents, setAgents] = useState<AgentProfile[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState<{ role: string; goal: string; model: string }>({ role: "", goal: "", model: "" });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const fetchAgents = async () => {
    try {
      setAgents(await listAgentProfiles());
    } catch { /* ignore */ }
  };

  useEffect(() => { fetchAgents(); }, []);

  const startEdit = (a: AgentProfile) => {
    setEditing(a.name);
    setForm({ role: a.role, goal: a.goal, model: a.model || "" });
    setError("");
  };

  const handleSave = async (name: string) => {
    setSaving(true);
    setError("");
    try {
      await updateAgentProfile(name, form);
      await fetchAgents();
      setEditing(null);
    } catch (e: any) {
      setError(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (a: AgentProfile, enabled: boolean) => {
    try {
      await updateAgentProfile(a.name, { enabled });
      await fetchAgents();
    } catch { /* ignore */ }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.6)" }}>
      <div className="w-full max-w-lg rounded-xl p-6 max-h-[85vh] overflow-y-auto" style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>Agent Team</h2>
          <button onClick={onClose} className="text-xl leading-none" style={{ color: "var(--text-secondary)" }}>✕</button>
        </div>

        {error && (
          <div className="mb-3 px-3 py-2 rounded text-xs" style={{ background: "#2d1215", color: "#fca5a5", border: "1px solid #5c1d22" }}>{error}</div>
        )}

        {agents.map((a) => (
          <div key={a.id} className="mb-3 p-3 rounded-lg" style={{ background: "var(--bg-primary)", border: "1px solid var(--border)" }}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{a.display_name}</span>
              <code className="text-[10px] px-1.5 py-0.5 rounded font-mono" style={{ background: "var(--bg-tertiary)", color: "var(--text-secondary)" }}>{a.name}</code>
            </div>
            <div className="text-xs mb-1" style={{ color: "var(--text-secondary)" }}>
              <strong>Role:</strong> {a.role}
            </div>
            <div className="text-xs mb-2" style={{ color: "var(--text-secondary)" }}>
              <strong>Goal:</strong> {a.goal}
            </div>

            {editing === a.name ? (
              <div>
                <label className="block text-[10px] font-medium mb-0.5" style={{ color: "var(--text-primary)" }}>Role</label>
                <input value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}
                  className="w-full mb-2 px-2 py-1 rounded text-xs outline-none" style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }} />

                <label className="block text-[10px] font-medium mb-0.5" style={{ color: "var(--text-primary)" }}>Goal</label>
                <input value={form.goal} onChange={(e) => setForm({ ...form, goal: e.target.value })}
                  className="w-full mb-2 px-2 py-1 rounded text-xs outline-none" style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }} />

                <label className="block text-[10px] font-medium mb-0.5" style={{ color: "var(--text-primary)" }}>Model (optional)</label>
                <input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })}
                  className="w-full mb-3 px-2 py-1 rounded text-xs outline-none" style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }} placeholder="Leave empty to follow parent" />

                <div className="flex gap-2">
                  <button onClick={() => handleSave(a.name)} disabled={saving}
                    className="text-[10px] px-3 py-1 rounded transition-opacity hover:opacity-80" style={{ background: "var(--accent)", color: "#fff" }}>
                    {saving ? "..." : "Save"}
                  </button>
                  <button onClick={() => setEditing(null)}
                    className="text-[10px] px-3 py-1 rounded transition-opacity hover:opacity-80" style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)" }}>
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <button onClick={() => startEdit(a)}
                  className="text-[10px] px-2 py-0.5 rounded transition-opacity hover:opacity-80" style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)" }}>
                  Edit
                </button>
                <button onClick={() => handleToggle(a, !a.enabled)}
                  className="text-[10px] px-2 py-0.5 rounded transition-opacity hover:opacity-80"
                  style={{ background: a.enabled ? "#065f46" : "#4b5563", color: "#fff" }}>
                  {a.enabled ? "Enabled" : "Disabled"}
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

import { useState, useEffect } from "react";
import {
  AgentProfile,
  listAgentProfiles,
  createAgentProfile,
  updateAgentProfile,
  deleteAgentProfile,
} from "../api/agents";

const ICON_OPTIONS = [
  "🔍", "📊", "💻", "📝", "🤖", "🧠", "🎨", "🔧", "📡", "🛡️",
  "⚙️", "🗂️", "📈", "🔬", "💡", "🎯", "🧪", "🏗️", "🌍", "🎭",
];

const AVAILABLE_TOOLS = [
  "bash", "read", "write", "edit", "glob", "grep",
  "web_search", "web_scrape", "browser", "sandbox",
  "shared_get", "shared_put", "shared_list",
];

interface Props {
  onClose: () => void;
}

type FormState = {
  display_name: string;
  role: string;
  goal: string;
  backstory: string;
  model: string;
  icon: string;
  tools: string[];
};

const emptyForm: FormState = {
  display_name: "", role: "", goal: "", backstory: "", model: "", icon: "🤖", tools: [],
};

export function AgentTeamPanel({ onClose }: Props) {
  const [agents, setAgents] = useState<AgentProfile[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [createName, setCreateName] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const fetchAgents = async () => {
    try { setAgents(await listAgentProfiles()); } catch { /* ignore */ }
  };

  useEffect(() => { fetchAgents(); }, []);

  const startEdit = (a: AgentProfile) => {
    setEditing(a.name);
    setForm({
      display_name: a.display_name,
      role: a.role,
      goal: a.goal,
      backstory: a.backstory || "",
      model: a.model || "",
      icon: a.icon || "🤖",
      tools: a.tools || [],
    });
    setError("");
  };

  const startCreate = () => {
    setShowCreate(true);
    setCreateName("");
    setForm(emptyForm);
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

  const handleCreate = async () => {
    if (!createName.trim() || !form.display_name.trim() || !form.role.trim() || !form.goal.trim()) {
      setError("Name, display name, role and goal are required");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await createAgentProfile({
        name: createName.trim().toLowerCase().replace(/\s+/g, "_"),
        display_name: form.display_name,
        role: form.role,
        goal: form.goal,
        backstory: form.backstory,
        model: form.model,
        icon: form.icon,
        tools: form.tools,
      });
      await fetchAgents();
      setShowCreate(false);
    } catch (e: any) {
      setError(e?.message || "Create failed");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (a: AgentProfile) => {
    if (!confirm(`Delete agent "${a.display_name}"?`)) return;
    try {
      await deleteAgentProfile(a.name);
      await fetchAgents();
    } catch (e: any) {
      setError(e?.message || "Delete failed");
    }
  };

  const handleToggle = async (a: AgentProfile) => {
    try {
      await updateAgentProfile(a.name, { enabled: !a.enabled });
      await fetchAgents();
    } catch { /* ignore */ }
  };

  const renderForm = (onSave: () => void, showNameField = false) => (
    <div className="space-y-2.5">
      {showNameField && (
        <>
          <label className="block text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>Agent ID</label>
          <input value={createName} onChange={(e) => setCreateName(e.target.value)}
            className="w-full px-2.5 py-1.5 rounded-lg text-xs outline-none transition-colors focus:ring-1"
            style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)", "--tw-ring-color": "var(--accent)" } as any}
            placeholder="e.g. designer, translator" />
        </>
      )}
      <div className="flex gap-3">
        <div className="flex-1">
          <label className="block text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>Display Name</label>
          <input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })}
            className="w-full px-2.5 py-1.5 rounded-lg text-xs outline-none"
            style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }} />
        </div>
        <div>
          <label className="block text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>Icon</label>
          <div className="flex flex-wrap gap-1 p-1.5 rounded-lg" style={{ background: "var(--bg-tertiary)", border: "1px solid var(--border)" }}>
            {ICON_OPTIONS.slice(0, 10).map((ic) => (
              <button key={ic} onClick={() => setForm({ ...form, icon: ic })}
                className="w-6 h-6 rounded text-sm flex items-center justify-center transition-all"
                style={{ background: form.icon === ic ? "var(--accent)" : "transparent", transform: form.icon === ic ? "scale(1.15)" : "scale(1)" }}>
                {ic}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div>
        <label className="block text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>Role</label>
        <input value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}
          className="w-full px-2.5 py-1.5 rounded-lg text-xs outline-none"
          style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }} />
      </div>
      <div>
        <label className="block text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>Goal</label>
        <textarea value={form.goal} onChange={(e) => setForm({ ...form, goal: e.target.value })} rows={2}
          className="w-full px-2.5 py-1.5 rounded-lg text-xs outline-none resize-none"
          style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }} />
      </div>
      <div>
        <label className="block text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>Backstory</label>
        <textarea value={form.backstory} onChange={(e) => setForm({ ...form, backstory: e.target.value })} rows={2}
          className="w-full px-2.5 py-1.5 rounded-lg text-xs outline-none resize-none"
          style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }} placeholder="Optional personality and expertise context" />
      </div>
      <div>
        <label className="block text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>Model Override</label>
        <input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })}
          className="w-full px-2.5 py-1.5 rounded-lg text-xs outline-none"
          style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }} placeholder="Leave empty to use default" />
      </div>
      <div>
        <label className="block text-[10px] font-semibold uppercase tracking-wider mb-1" style={{ color: "var(--text-secondary)" }}>
          Tools {form.tools.length === 0 && <span style={{ color: "var(--text-secondary)", fontWeight: 400, textTransform: "none" }}>(all enabled)</span>}
        </label>
        <div className="flex flex-wrap gap-1">
          {AVAILABLE_TOOLS.map((t) => {
            const selected = form.tools.includes(t);
            return (
              <button key={t} type="button" onClick={() => {
                setForm({ ...form, tools: selected ? form.tools.filter((x) => x !== t) : [...form.tools, t] });
              }} className="text-[10px] px-1.5 py-0.5 rounded transition-all"
                style={{
                  background: selected ? "var(--accent)" : "var(--bg-tertiary)",
                  color: selected ? "var(--text-on-accent)" : "var(--text-secondary)",
                  border: `1px solid ${selected ? "var(--accent)" : "var(--border)"}`,
                }}>
                {t}
              </button>
            );
          })}
          {form.tools.length > 0 && (
            <button type="button" onClick={() => setForm({ ...form, tools: [] })}
              className="text-[10px] px-1.5 py-0.5 rounded transition-all"
              style={{ background: "var(--bg-tertiary)", color: "var(--text-secondary)", border: "1px solid var(--border)" }}>
              clear
            </button>
          )}
        </div>
      </div>
      <div className="flex gap-2 pt-1">
        <button onClick={onSave} disabled={saving}
          className="text-xs px-4 py-1.5 rounded-lg font-medium transition-all hover:opacity-80"
          style={{ background: "var(--accent)", color: "var(--text-on-accent)" }}>
          {saving ? "Saving..." : "Save"}
        </button>
        <button onClick={() => { setEditing(null); setShowCreate(false); }}
          className="text-xs px-4 py-1.5 rounded-lg transition-all hover:opacity-80"
          style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)" }}>
          Cancel
        </button>
      </div>
    </div>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.6)" }}>
      <div className="w-full max-w-xl rounded-xl max-h-[88vh] flex flex-col overflow-hidden"
        style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", boxShadow: "0 25px 60px rgba(0,0,0,0.4)" }}>
        <div className="flex items-center justify-between px-5 py-4 shrink-0" style={{ borderBottom: "1px solid var(--border)" }}>
          <div className="flex items-center gap-2">
            <span className="text-lg">🤖</span>
            <h2 className="text-base font-bold" style={{ color: "var(--text-primary)" }}>Agent Team</h2>
            <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium"
              style={{ background: "var(--bg-tertiary)", color: "var(--text-secondary)" }}>
              {agents.filter((a) => a.enabled).length}/{agents.length} active
            </span>
          </div>
          <button onClick={onClose} className="text-lg leading-none opacity-60 hover:opacity-100 transition-opacity" style={{ color: "var(--text-secondary)" }}>
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
          {error && (
            <div className="px-3 py-2 rounded-lg text-xs" style={{ background: "var(--danger-bg)", color: "var(--danger)", border: "1px solid var(--danger-border)" }}>
              {error}
            </div>
          )}

          {showCreate && renderForm(handleCreate, true)}

          {agents.map((a) => (
            <div key={a.id} className="rounded-xl transition-all"
              style={{
                background: "var(--bg-primary)",
                border: `1px solid ${a.enabled ? "var(--border)" : "transparent"}`,
                opacity: a.enabled ? 1 : 0.55,
              }}>
              {editing === a.name ? (
                <div className="p-4">{renderForm(() => handleSave(a.name))}</div>
              ) : (
                <div className="p-3.5">
                  <div className="flex items-center gap-3 mb-2">
                    <span className="text-xl w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                      style={{ background: "var(--bg-tertiary)" }}>
                      {a.icon || "🤖"}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold truncate" style={{ color: "var(--text-primary)" }}>
                          {a.display_name}
                        </span>
                        {a.model && (
                          <span className="text-[9px] px-1.5 py-0.5 rounded font-mono" style={{ background: "var(--accent-bg)", color: "var(--accent)" }}>
                            {a.model}
                          </span>
                        )}
                      </div>
                      <code className="text-[10px] font-mono" style={{ color: "var(--text-secondary)" }}>{a.name}</code>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <button onClick={() => startEdit(a)} title="Edit"
                        className="text-[10px] px-2 py-1 rounded-md transition-opacity hover:opacity-80"
                        style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)" }}>
                        Edit
                      </button>
                      <button onClick={() => handleToggle(a)} title={a.enabled ? "Disable" : "Enable"}
                        className="text-[10px] px-2 py-1 rounded-md transition-opacity hover:opacity-80"
                        style={{ background: a.enabled ? "var(--success-bg)" : "var(--bg-elevated)", color: "var(--text-on-accent)" }}>
                        {a.enabled ? "On" : "Off"}
                      </button>
                      {!a.is_default && (
                        <button onClick={() => handleDelete(a)} title="Delete"
                          className="text-[10px] px-2 py-1 rounded-md transition-opacity hover:opacity-80"
                          style={{ background: "var(--danger-bg)", color: "var(--danger)" }}>
                          Del
                        </button>
                      )}
                    </div>
                  </div>
                  <p className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                    {a.role} — {a.goal}
                  </p>
                  {a.tools && a.tools.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {a.tools.map((t) => (
                        <span key={t} className="text-[9px] px-1.5 py-0.5 rounded font-mono"
                          style={{ background: "var(--bg-tertiary)", color: "var(--text-secondary)", border: "1px solid var(--border)" }}>
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}

          {agents.length === 0 && !showCreate && (
            <div className="text-center py-8">
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>No agents yet</p>
            </div>
          )}
        </div>

        {!showCreate && (
          <div className="px-5 py-3 shrink-0" style={{ borderTop: "1px solid var(--border)" }}>
            <button onClick={startCreate}
              className="w-full py-2 rounded-lg text-xs font-medium transition-all hover:opacity-80"
              style={{ background: "var(--accent)", color: "var(--text-on-accent)" }}>
              + New Agent
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

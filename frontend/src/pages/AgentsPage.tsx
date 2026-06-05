import { useState, useEffect } from "react";
import {
  Plus,
  Pencil,
  Trash2,
  Loader2,
  ToggleLeft,
  ToggleRight,
  Bot,
} from "lucide-react";
import {
  AgentProfile,
  listAgentProfiles,
  createAgentProfile,
  updateAgentProfile,
  deleteAgentProfile,
  listLearningAgents,
  listAgentMemory,
  deleteAgentMemory,
  getAgentStats,
  AgentMemoryItem,
  AgentTaskStats,
  ToolInfo,
  listTools,
  getDefaultToolPermissions,
  setDefaultToolPermissions,
} from "../api/agents";
import { Button, Input, Textarea, ConfirmDialog, EmptyState } from "../components/ui";
import { toast } from "../components/ui/Toast";
import { cn } from "../lib/cn";

const ICON_OPTIONS = [
  "🔍", "📊", "💻", "📝", "🤖", "🧠", "🎨", "🔧", "📡", "🛡️",
  "⚙️", "🗂️", "📈", "🔬", "💡", "🎯", "🧪", "🏗️", "🌍", "🎭",
];

const AVAILABLE_TOOLS = [
  "bash",
  "read",
  "write",
  "edit",
  "glob",
  "grep",
  "web_search",
  "web_scrape",
  "browser",
  "sandbox",
  "shared_get",
  "shared_put",
  "shared_list",
];

type Permission = "auto" | "confirm" | "deny";

type FormState = {
  display_name: string;
  role: string;
  goal: string;
  backstory: string;
  model: string;
  icon: string;
  tool_permissions: Record<string, Permission>;
};

const emptyForm: FormState = {
  display_name: "",
  role: "",
  goal: "",
  backstory: "",
  model: "",
  icon: "🤖",
  tool_permissions: {},
};

const PERM_LABELS: Record<Permission, string> = { auto: "Auto", confirm: "Confirm", deny: "Deny" };
const PERM_COLORS: Record<Permission, string> = {
  auto: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  confirm: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  deny: "bg-red-500/15 text-red-400 border-red-500/30",
};
const PERM_COLORS_ACTIVE: Record<Permission, string> = {
  auto: "bg-emerald-500 text-white border-emerald-500",
  confirm: "bg-amber-500 text-white border-amber-500",
  deny: "bg-red-500 text-white border-red-500",
};
const DEFAULT_KEY = "__default__";

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentProfile[]>([]);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [createName, setCreateName] = useState("");
  const [form, setForm] = useState<FormState>(emptyForm);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<AgentProfile | null>(null);

  const [learningAgents, setLearningAgents] = useState<string[]>([]);
  const [agentStats, setAgentStats] = useState<AgentTaskStats | null>(null);
  const [agentMemories, setAgentMemories] = useState<AgentMemoryItem[]>([]);
  const [loadingLearn, setLoadingLearn] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [toolInfoList, setToolInfoList] = useState<ToolInfo[]>([]);
  const [defaultPerms, setDefaultPerms] = useState<Record<string, Permission>>({});
  const [editingDefault, setEditingDefault] = useState(false);
  const [defaultForm, setDefaultForm] = useState<Record<string, Permission>>({});

  const fetchAgents = async () => {
    try {
      setAgents(await listAgentProfiles());
    } catch {}
  };

  useEffect(() => {
    fetchAgents().then(() => setInitialLoading(false));
    listLearningAgents().then(setLearningAgents).catch(() => {});
    listTools().then(setToolInfoList).catch(() => {});
    getDefaultToolPermissions().then((r) => setDefaultPerms((r.tool_permissions || {}) as Record<string, Permission>)).catch(() => {});
  }, []);

  const selected = agents.find((a) => a.name === selectedName) || null;

  useEffect(() => {
    if (selected && learningAgents.includes(selected.name)) {
      loadLearning(selected.name);
    } else {
      setAgentStats(null);
      setAgentMemories([]);
    }
  }, [selectedName, learningAgents]);

  const loadLearning = async (agentName: string) => {
    setLoadingLearn(true);
    try {
      const [stats, memories] = await Promise.all([
        getAgentStats(agentName),
        listAgentMemory(agentName, 20),
      ]);
      setAgentStats(stats);
      setAgentMemories(memories);
    } catch {
      setAgentStats(null);
      setAgentMemories([]);
    } finally {
      setLoadingLearn(false);
    }
  };

  const handleDeleteMemory = async (key: string) => {
    try {
      await deleteAgentMemory(key);
      setAgentMemories((prev) => prev.filter((m) => m.key !== key));
    } catch {}
  };

  const startEdit = () => {
    if (!selected) return;
    setForm({
      display_name: selected.display_name,
      role: selected.role,
      goal: selected.goal,
      backstory: selected.backstory || "",
      model: selected.model || "",
      icon: selected.icon || "🤖",
      tool_permissions: (selected.tool_permissions || {}) as Record<string, Permission>,
    });
    setEditing(true);
    setError("");
  };

  const startCreate = () => {
    setShowCreate(true);
    setCreateName("");
    setForm(emptyForm);
    setError("");
    setSelectedName(null);
  };

  const handleSave = async () => {
    if (!selected) return;
    setSaving(true);
    setError("");
    try {
      await updateAgentProfile(selected.name, form);
      toast.success("Agent saved");
      await fetchAgents();
      setEditing(false);
    } catch (e: any) {
      setError(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleCreate = async () => {
    if (
      !createName.trim() ||
      !form.display_name.trim() ||
      !form.role.trim() ||
      !form.goal.trim()
    ) {
      setError("Name, display name, role and goal are required");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const created = await createAgentProfile({
        name: createName.trim().toLowerCase().replace(/\s+/g, "_"),
        display_name: form.display_name,
        role: form.role,
        goal: form.goal,
        backstory: form.backstory,
        model: form.model,
        icon: form.icon,
        tool_permissions: form.tool_permissions,
      });
      toast.success("Agent created");
      await fetchAgents();
      setShowCreate(false);
      setSelectedName(created.name);
    } catch (e: any) {
      setError(e?.message || "Create failed");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteAgentProfile(deleteTarget.name);
      toast.success("Agent deleted");
      if (selectedName === deleteTarget.name) setSelectedName(null);
      await fetchAgents();
    } catch (e: any) {
      toast.error(e?.message || "Delete failed");
    } finally {
      setDeleteTarget(null);
    }
  };

  const handleToggle = async (a: AgentProfile) => {
    try {
      await updateAgentProfile(a.name, { enabled: !a.enabled });
      await fetchAgents();
    } catch {}
  };

  const cancelForm = () => {
    setEditing(false);
    setShowCreate(false);
    setEditingDefault(false);
    setError("");
  };

  const startEditDefault = () => {
    setDefaultForm({ ...defaultPerms });
    setEditingDefault(true);
    setSelectedName(null);
    setEditing(false);
    setShowCreate(false);
    setError("");
  };

  const handleSaveDefault = async () => {
    setSaving(true);
    setError("");
    try {
      await setDefaultToolPermissions(defaultForm);
      setDefaultPerms({ ...defaultForm });
      toast.success("Default permissions saved");
      setEditingDefault(false);
    } catch (e: any) {
      setError(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const renderForm = () => (
    <div className="space-y-3">
      {showCreate && (
        <Input
          label="Agent ID"
          value={createName}
          onChange={(e) => setCreateName(e.target.value)}
          placeholder="e.g. designer, translator"
        />
      )}
      <div className="flex gap-3 items-end">
        <div className="flex-1">
          <Input
            label="Display Name"
            value={form.display_name}
            onChange={(e) => setForm({ ...form, display_name: e.target.value })}
          />
        </div>
        <div>
          <label className="block text-[11px] font-medium text-[var(--text-secondary)] mb-1.5">
            Icon
          </label>
          <div className="flex flex-wrap gap-0.5 p-1.5 rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border)] max-w-[200px]">
            {ICON_OPTIONS.map((ic) => (
              <button
                key={ic}
                type="button"
                onClick={() => setForm({ ...form, icon: ic })}
                className={cn(
                  "w-6 h-6 rounded text-sm flex items-center justify-center transition-all",
                  form.icon === ic
                    ? "bg-[var(--brand)] scale-110"
                    : "hover:bg-[var(--bg-elevated)]",
                )}
              >
                {ic}
              </button>
            ))}
          </div>
        </div>
      </div>
      <Input
        label="Role"
        value={form.role}
        onChange={(e) => setForm({ ...form, role: e.target.value })}
      />
      <Textarea
        label="Goal"
        value={form.goal}
        onChange={(e) => setForm({ ...form, goal: e.target.value })}
        rows={2}
      />
      <Textarea
        label="Backstory"
        value={form.backstory}
        onChange={(e) => setForm({ ...form, backstory: e.target.value })}
        rows={2}
        placeholder="Optional personality and expertise context"
      />
      <Input
        label="Model Override"
        value={form.model}
        onChange={(e) => setForm({ ...form, model: e.target.value })}
        placeholder="Leave empty to use default"
      />
      <div>
        <label className="block text-[11px] font-medium text-[var(--text-secondary)] mb-1.5">
          Tool Permissions
        </label>
        <div className="space-y-1">
          {(toolInfoList.length > 0 ? toolInfoList : AVAILABLE_TOOLS.map((t) => ({ name: t, description: "", default_permission: "auto" as const }))).map((ti) => {
            const perm = form.tool_permissions[ti.name];
            const resolved: Permission = perm || (ti.default_permission as Permission);
            const isExplicit = !!perm;
            return (
              <div key={ti.name} className="flex items-center gap-2">
                <span className={cn(
                  "text-[10px] font-mono w-24 shrink-0 truncate",
                  resolved === "deny" ? "text-[var(--text-tertiary)] line-through" : "text-[var(--text-secondary)]",
                )}>
                  {ti.name}
                </span>
                <div className="flex gap-0.5">
                  {(["auto", "confirm", "deny"] as Permission[]).map((p) => (
                    <button
                      key={p}
                      type="button"
                      onClick={() => {
                        const tp = { ...form.tool_permissions, [ti.name]: p };
                        setForm({ ...form, tool_permissions: tp });
                      }}
                      className={cn(
                        "text-[9px] px-1.5 py-0.5 rounded font-medium border transition-colors",
                        resolved === p
                          ? PERM_COLORS_ACTIVE[p]
                          : PERM_COLORS[p],
                        !isExplicit && resolved === p && "opacity-60",
                      )}
                      title={!isExplicit && resolved === p ? "Default (click to override)" : PERM_LABELS[p]}
                    >
                      {PERM_LABELS[p]}
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <div className="flex gap-2 pt-1">
        <Button
          variant="brand"
          loading={saving}
          onClick={showCreate ? handleCreate : handleSave}
        >
          {showCreate ? "Create" : "Save"}
        </Button>
        <Button variant="ghost" onClick={cancelForm}>
          Cancel
        </Button>
      </div>
    </div>
  );

  const activeCount = agents.filter((a) => a.enabled).length;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <header className="flex items-center justify-between px-6 h-12 border-b border-[var(--border)] bg-[var(--bg-secondary)] shrink-0">
        <div className="flex items-center gap-3">
          <h1 className="text-sm font-semibold text-[var(--text-primary)]">
            Agent Team
          </h1>
          <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium bg-[var(--bg-tertiary)] text-[var(--text-secondary)]">
            {activeCount}/{agents.length} active
          </span>
        </div>
        {!showCreate && !editing && (
          <Button variant="brand" size="sm" onClick={startCreate}>
            <Plus size={14} /> New Agent
          </Button>
        )}
      </header>

      {/* Body: left-right split */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: agent list */}
        <div className="w-64 lg:w-72 shrink-0 border-r border-[var(--border)] flex flex-col bg-[var(--bg-secondary)]">
          <div className="flex-1 overflow-y-auto p-2">
            {initialLoading && (
              <div className="flex items-center justify-center py-8 text-xs text-[var(--text-tertiary)]">
                <Loader2 size={14} className="animate-spin mr-2" /> Loading…
              </div>
            )}
            {!initialLoading && agents.length === 0 && (
              <div className="px-2 py-8">
                <EmptyState
                  icon={<Bot size={24} className="text-[var(--text-tertiary)]" />}
                  title="No agents"
                  description="Create your first agent."
                />
              </div>
            )}
            {!initialLoading && (
            <div className="space-y-0.5">
              {agents.map((a) => (
                <button
                  key={a.id}
                  onClick={() => {
                    setSelectedName(a.name);
                    setEditing(false);
                    setShowCreate(false);
                    setEditingDefault(false);
                  }}
                  className={cn(
                    "w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-left transition-all",
                    selectedName === a.name
                      ? "bg-[var(--bg-tertiary)] ring-1 ring-[var(--border-strong)]"
                      : "hover:bg-[var(--bg-tertiary)]/60",
                    !a.enabled && "opacity-50",
                  )}
                >
                  <span className="text-lg w-8 h-8 rounded-lg flex items-center justify-center shrink-0 bg-[var(--bg-elevated)]">
                    {a.icon || "🤖"}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] font-medium text-[var(--text-primary)] truncate">
                      {a.display_name}
                    </div>
                    <div className="text-[10px] font-mono text-[var(--text-tertiary)] truncate">
                      {a.name}
                      {a.model && (
                        <span className="ml-1 text-[var(--accent)]">
                          {a.model}
                        </span>
                      )}
                    </div>
                  </div>
                  <div
                    className={cn(
                      "w-2 h-2 rounded-full shrink-0",
                      a.enabled ? "bg-[var(--success)]" : "bg-[var(--text-tertiary)]",
                    )}
                  />
                </button>
              ))}
            </div>
            )}
            {!initialLoading && (
              <div className="mt-3 pt-3 border-t border-[var(--border)]">
                <button
                  onClick={startEditDefault}
                  className={cn(
                    "w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-left transition-all",
                    editingDefault
                      ? "bg-[var(--bg-tertiary)] ring-1 ring-[var(--border-strong)]"
                      : "hover:bg-[var(--bg-tertiary)]/60",
                  )}
                >
                  <span className="text-lg w-8 h-8 rounded-lg flex items-center justify-center shrink-0 bg-[var(--bg-elevated)]">
                    ⚙️
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] font-medium text-[var(--text-primary)]">
                      Default
                    </div>
                    <div className="text-[10px] text-[var(--text-tertiary)]">
                      Default tool permissions
                    </div>
                  </div>
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Right: detail panel */}
        <div className="flex-1 overflow-y-auto bg-[var(--bg-primary)]">
          {editingDefault && (
            <div className="max-w-2xl mx-auto p-6">
              <h2 className="text-lg font-semibold text-[var(--text-primary)] mb-4">
                Default Tool Permissions
              </h2>
              <p className="text-xs text-[var(--text-tertiary)] mb-4">
                These permissions apply when an agent does not have its own override.
              </p>
              <div className="space-y-1">
                {(toolInfoList.length > 0 ? toolInfoList : AVAILABLE_TOOLS.map((t) => ({ name: t, description: "", default_permission: "auto" as Permission }))).map((ti) => {
                  const perm = defaultForm[ti.name];
                  const resolved: Permission = perm || (ti.default_permission as Permission) || "auto";
                  return (
                    <div key={ti.name} className="flex items-center gap-2">
                      <span className="text-[10px] font-mono w-28 shrink-0 truncate text-[var(--text-secondary)]">
                        {ti.name}
                      </span>
                      {(["auto", "confirm", "deny"] as Permission[]).map((p) => (
                        <button
                          key={p}
                          type="button"
                          onClick={() => setDefaultForm({ ...defaultForm, [ti.name]: p })}
                          className={cn(
                            "text-[9px] px-1.5 py-0.5 rounded font-medium border transition-colors",
                            resolved === p ? PERM_COLORS_ACTIVE[p] : PERM_COLORS[p],
                          )}
                        >
                          {PERM_LABELS[p]}
                        </button>
                      ))}
                    </div>
                  );
                })}
              </div>
              <div className="flex gap-2 pt-4">
                <Button variant="brand" loading={saving} onClick={handleSaveDefault}>
                  Save
                </Button>
                <Button variant="ghost" onClick={cancelForm}>
                  Cancel
                </Button>
              </div>
              {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
            </div>
          )}
          {!selected && !showCreate && !editingDefault && (
            <div className="flex items-center justify-center h-full">
              <EmptyState
                icon={
                  <span className="text-3xl">
                    {agents.length > 0 ? "👈" : "🤖"}
                  </span>
                }
                title={agents.length > 0 ? "Select an agent" : "No agents yet"}
                description={
                  agents.length > 0
                    ? "Choose from the list to view details"
                    : "Create your first agent to get started"
                }
                action={
                  agents.length === 0 ? (
                    <Button variant="brand" size="sm" onClick={startCreate}>
                      <Plus size={14} /> New Agent
                    </Button>
                  ) : undefined
                }
              />
            </div>
          )}

          {showCreate && (
            <div className="max-w-lg mx-auto p-6">
              <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-4">
                Create New Agent
              </h2>
              {error && (
                <div className="mb-3 px-3 py-2 rounded-lg bg-[var(--danger-bg)] border border-[var(--danger-border)] text-xs text-[var(--danger)]">
                  {error}
                </div>
              )}
              {renderForm()}
            </div>
          )}

          {selected && !showCreate && (
            <div className="max-w-lg mx-auto p-6">
              {error && (
                <div className="mb-3 px-3 py-2 rounded-lg bg-[var(--danger-bg)] border border-[var(--danger-border)] text-xs text-[var(--danger)]">
                  {error}
                </div>
              )}

              {editing ? (
                <>
                  <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-4">
                    Edit {selected.display_name}
                  </h2>
                  {renderForm()}
                </>
              ) : (
                <>
                  {/* Agent header */}
                  <div className="flex items-start gap-4 mb-5">
                    <span className="text-3xl w-14 h-14 rounded-xl flex items-center justify-center shrink-0 bg-[var(--bg-tertiary)] border border-[var(--border)]">
                      {selected.icon || "🤖"}
                    </span>
                    <div className="flex-1 min-w-0">
                      <h2 className="text-lg font-semibold text-[var(--text-primary)]">
                        {selected.display_name}
                      </h2>
                      <div className="flex items-center gap-2 mt-1 flex-wrap">
                        <code className="text-[11px] font-mono text-[var(--text-tertiary)] bg-[var(--bg-tertiary)] px-1.5 py-0.5 rounded">
                          {selected.name}
                        </code>
                        {selected.model && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded font-mono bg-[var(--accent-bg)] text-[var(--accent)]">
                            {selected.model}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <Button
                        size="xs"
                        variant="ghost"
                        onClick={() => startEdit()}
                      >
                        <Pencil size={12} />
                      </Button>
                      <button
                        onClick={() => handleToggle(selected)}
                        title={selected.enabled ? "Disable" : "Enable"}
                        className={cn(
                          "flex items-center gap-1 h-7 px-2.5 rounded-md text-[11px] font-medium border transition-colors",
                          selected.enabled
                            ? "bg-[var(--success-bg)] text-[var(--success)] border-[var(--success-border)] hover:bg-[var(--success)] hover:text-white"
                            : "bg-[var(--bg-elevated)] text-[var(--text-tertiary)] border-[var(--border)] hover:text-[var(--text-secondary)]",
                        )}
                      >
                        {selected.enabled ? (
                          <ToggleRight size={14} />
                        ) : (
                          <ToggleLeft size={14} />
                        )}
                        {selected.enabled ? "On" : "Off"}
                      </button>
                      {!selected.is_default && (
                        <Button
                          size="xs"
                          variant="ghost"
                          onClick={() => setDeleteTarget(selected)}
                          className="text-[var(--danger)] hover:text-[var(--danger)] hover:bg-[var(--danger-bg)]"
                        >
                          <Trash2 size={12} />
                        </Button>
                      )}
                    </div>
                  </div>

                  {/* Details */}
                  <div className="space-y-4">
                    <div>
                      <label className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                        Role
                      </label>
                      <p className="text-sm text-[var(--text-primary)] mt-1">
                        {selected.role}
                      </p>
                    </div>
                    <div>
                      <label className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                        Goal
                      </label>
                      <p className="text-sm text-[var(--text-secondary)] mt-1 whitespace-pre-wrap leading-relaxed">
                        {selected.goal}
                      </p>
                    </div>
                    {selected.backstory && (
                      <div>
                        <label className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                          Backstory
                        </label>
                        <p className="text-sm text-[var(--text-secondary)] mt-1 whitespace-pre-wrap leading-relaxed">
                          {selected.backstory}
                        </p>
                      </div>
                    )}
                    {(() => {
                      const perms = selected.tool_permissions || {};
                      const auto = Object.entries(perms).filter(([, v]) => v === "auto");
                      const confirmed = Object.entries(perms).filter(([, v]) => v === "confirm");
                      if (!auto.length && !confirmed.length) return null;
                      return (
                        <div>
                          <label className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                            Permissions
                          </label>
                          <div className="flex flex-wrap gap-1 mt-1.5">
                            {auto.map(([t]) => (
                              <span key={t} className="text-[10px] px-1.5 py-0.5 rounded font-mono bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                                {t}
                              </span>
                            ))}
                            {confirmed.map(([t]) => (
                              <span key={t} className="text-[10px] px-1.5 py-0.5 rounded font-mono bg-amber-500/15 text-amber-400 border border-amber-500/30">
                                {t} (confirm)
                              </span>
                            ))}
                          </div>
                        </div>
                      );
                    })()}

                    {/* Learning Stats */}
                    {learningAgents.includes(selected.name) && (
                      <div className="mt-2 pt-4 border-t border-[var(--border)]">
                        <div className="flex items-center gap-2 mb-3">
                          <span className="text-sm">🧠</span>
                          <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                            Learning Stats
                          </span>
                        </div>
                        {loadingLearn && (
                          <div className="flex items-center gap-2 py-2 text-xs text-[var(--text-tertiary)]">
                            <Loader2 size={12} className="animate-spin" />{" "}
                            Loading…
                          </div>
                        )}
                        {agentStats && !loadingLearn && (
                          <div className="space-y-3">
                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                              <div className="rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border)] px-3 py-2 text-center">
                                <div className="text-lg font-semibold text-[var(--text-primary)]">
                                  {agentStats.total}
                                </div>
                                <div className="text-[10px] text-[var(--text-tertiary)]">
                                  Tasks
                                </div>
                              </div>
                              <div className="rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border)] px-3 py-2 text-center">
                                <div className="text-lg font-semibold text-[var(--success)]">
                                  {agentStats.success_rate}%
                                </div>
                                <div className="text-[10px] text-[var(--text-tertiary)]">
                                  Success
                                </div>
                              </div>
                              <div className="rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border)] px-3 py-2 text-center">
                                <div className="text-lg font-semibold text-[var(--text-primary)]">
                                  {agentStats.avg_elapsed}s
                                </div>
                                <div className="text-[10px] text-[var(--text-tertiary)]">
                                  Avg Time
                                </div>
                              </div>
                              <div className="rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border)] px-3 py-2 text-center">
                                <div className="text-lg font-semibold text-[var(--text-primary)]">
                                  {agentStats.avg_tokens}
                                </div>
                                <div className="text-[10px] text-[var(--text-tertiary)]">
                                  Avg Tokens
                                </div>
                              </div>
                            </div>
                            {agentMemories.length > 0 && (
                              <div>
                                <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)] mb-1.5">
                                  Memory ({agentMemories.length})
                                </div>
                                <div className="space-y-1 max-h-48 overflow-y-auto">
                                  {agentMemories.map((m) => (
                                    <div
                                      key={m.key}
                                      className="flex items-start gap-1.5 group"
                                    >
                                      <span
                                        className={cn(
                                          "text-[9px] px-1.5 py-0.5 rounded shrink-0 font-mono",
                                          m.source === "llm"
                                            ? "bg-[var(--accent-bg)] text-[var(--accent)]"
                                            : "bg-[var(--bg-secondary)] text-[var(--text-tertiary)]",
                                        )}
                                      >
                                        {m.source || "rule"}
                                      </span>
                                      <span className="text-[11px] flex-1 leading-relaxed truncate text-[var(--text-secondary)]">
                                        {m.content}
                                      </span>
                                      <button
                                        onClick={() =>
                                          handleDeleteMemory(m.key)
                                        }
                                        className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0 p-0.5 rounded text-[var(--danger)] hover:bg-[var(--danger-bg)]"
                                        title="Delete"
                                      >
                                        <Trash2 size={10} />
                                      </button>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                        {!agentStats &&
                          !loadingLearn &&
                          learningAgents.includes(selected.name) && (
                            <p className="text-[11px] text-[var(--text-tertiary)]">
                              No data available
                            </p>
                          )}
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        title={`Delete agent "${deleteTarget?.display_name}"?`}
        description="This permanently removes the agent profile and its learning data."
        confirmText="Delete"
        tone="danger"
        onConfirm={handleDelete}
      />
    </div>
  );
}

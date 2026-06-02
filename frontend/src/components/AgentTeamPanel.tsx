import { useState, useEffect } from "react";
import { Plus, Pencil, Trash2, Loader2 } from "lucide-react";
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
} from "../api/agents";
import {
  Modal,
  Button,
  Input,
  Textarea,
  ConfirmDialog,
  EmptyState,
} from "./ui";
import { toast } from "./ui/Toast";
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

interface Props {
  onClose: () => void;
  /** Render inline (no modal wrapper) for use in a dedicated page. */
  inline?: boolean;
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
  display_name: "",
  role: "",
  goal: "",
  backstory: "",
  model: "",
  icon: "🤖",
  tools: [],
};

export function AgentTeamPanel({ onClose, inline = false }: Props) {
  const [agents, setAgents] = useState<AgentProfile[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [createName, setCreateName] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const [learningAgents, setLearningAgents] = useState<string[]>([]);
  const [selectedLearnAgent, setSelectedLearnAgent] = useState("");
  const [agentStats, setAgentStats] = useState<AgentTaskStats | null>(null);
  const [agentMemories, setAgentMemories] = useState<AgentMemoryItem[]>([]);
  const [loadingLearn, setLoadingLearn] = useState(false);

  const [deleteTarget, setDeleteTarget] = useState<AgentProfile | null>(null);

  const fetchAgents = async () => {
    try {
      setAgents(await listAgentProfiles());
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    fetchAgents();
  }, []);

  useEffect(() => {
    listLearningAgents().then(setLearningAgents).catch(() => {});
  }, []);

  const loadLearning = async (agentName: string) => {
    setSelectedLearnAgent(agentName);
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
    } catch {
      /* ignore */
    }
  };

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
      toast.success("Agent saved");
      await fetchAgents();
      setEditing(null);
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
      toast.success("Agent created");
      await fetchAgents();
      setShowCreate(false);
    } catch (e: any) {
      setError(e?.message || "Create failed");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (a: AgentProfile) => {
    try {
      await deleteAgentProfile(a.name);
      toast.success("Agent deleted");
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
    } catch {
      /* ignore */
    }
  };

  const cancelForm = () => {
    setEditing(null);
    setShowCreate(false);
  };

  const renderForm = (onSave: () => void, showNameField = false) => (
    <div className="space-y-3">
      {showNameField && (
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
          Tools{" "}
          {form.tools.length === 0 && (
            <span className="font-normal text-[var(--text-tertiary)]">
              (all enabled)
            </span>
          )}
        </label>
        <div className="flex flex-wrap gap-1">
          {AVAILABLE_TOOLS.map((t) => {
            const selected = form.tools.includes(t);
            return (
              <button
                key={t}
                type="button"
                onClick={() =>
                  setForm({
                    ...form,
                    tools: selected
                      ? form.tools.filter((x) => x !== t)
                      : [...form.tools, t],
                  })
                }
                className={cn(
                  "text-[10px] px-2 py-1 rounded-md font-mono transition-colors",
                  selected
                    ? "bg-[var(--brand)] text-white"
                    : "bg-[var(--bg-tertiary)] text-[var(--text-secondary)] border border-[var(--border)] hover:text-[var(--text-primary)]",
                )}
              >
                {t}
              </button>
            );
          })}
          {form.tools.length > 0 && (
            <button
              type="button"
              onClick={() => setForm({ ...form, tools: [] })}
              className="text-[10px] px-2 py-1 rounded-md bg-[var(--bg-tertiary)] text-[var(--text-tertiary)] border border-[var(--border)] hover:text-[var(--text-secondary)]"
            >
              clear
            </button>
          )}
        </div>
      </div>
      <div className="flex gap-2 pt-1">
        <Button variant="brand" loading={saving} onClick={onSave}>
          Save
        </Button>
        <Button variant="ghost" onClick={cancelForm}>
          Cancel
        </Button>
      </div>
    </div>
  );

  const headerLabel = (
    <div className="flex items-center gap-2">
      <span>🤖</span>
      <span>Agent Team</span>
      <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium bg-[var(--bg-tertiary)] text-[var(--text-secondary)] ml-1">
        {agents.filter((a) => a.enabled).length}/{agents.length} active
      </span>
    </div>
  );

  const newAgentButton = !showCreate && !editing ? (
    <Button variant="brand" onClick={startCreate}>
      <Plus size={14} /> New Agent
    </Button>
  ) : undefined;

  const bodyContent = (
    <>
      {error && (
        <div className="mb-3 px-3 py-2 rounded-lg bg-[var(--danger-bg)] border border-[var(--danger-border)] text-xs text-[var(--danger)]">
          {error}
        </div>
      )}

      {showCreate && (
        <div className="mb-4 p-4 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border)]">
          {renderForm(handleCreate, true)}
        </div>
      )}

      <div className="space-y-2">
        {agents.length === 0 && !showCreate && (
          <EmptyState
            icon={<span className="text-2xl">🤖</span>}
            title="No agents yet"
            description="Create your first agent profile to enable multi-agent delegation."
            action={
              <Button variant="brand" size="sm" onClick={startCreate}>
                <Plus size={14} /> New Agent
              </Button>
            }
          />
        )}

        {agents.map((a) => (
            <div
              key={a.id}
              className={cn(
                "rounded-xl transition-all border",
                a.enabled
                  ? "bg-[var(--bg-tertiary)] border-[var(--border)]"
                  : "bg-[var(--bg-tertiary)] border-transparent opacity-60",
              )}
            >
              {editing === a.name ? (
                <div className="p-4">{renderForm(() => handleSave(a.name))}</div>
              ) : (
                <div className="p-3.5">
                  <div className="flex items-center gap-3 mb-2">
                    <span className="text-xl w-9 h-9 rounded-lg flex items-center justify-center shrink-0 bg-[var(--bg-elevated)]">
                      {a.icon || "🤖"}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-semibold text-[var(--text-primary)] truncate">
                          {a.display_name}
                        </span>
                        {a.model && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded font-mono bg-[var(--accent-bg)] text-[var(--accent)]">
                            {a.model}
                          </span>
                        )}
                      </div>
                      <code className="text-[10px] font-mono text-[var(--text-tertiary)]">
                        {a.name}
                      </code>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <Button
                        size="xs"
                        variant="ghost"
                        onClick={() => startEdit(a)}
                        title="Edit"
                      >
                        <Pencil size={12} />
                      </Button>
                      <button
                        onClick={() => handleToggle(a)}
                        title={a.enabled ? "Disable" : "Enable"}
                        className={cn(
                          "h-7 px-2 rounded-md text-[10px] font-medium border transition-colors",
                          a.enabled
                            ? "bg-[var(--success-bg)] text-[var(--success)] border-[var(--success-border)] hover:bg-[var(--success)] hover:text-white"
                            : "bg-[var(--bg-elevated)] text-[var(--text-tertiary)] border-[var(--border)] hover:text-[var(--text-secondary)]",
                        )}
                      >
                        {a.enabled ? "On" : "Off"}
                      </button>
                      {!a.is_default && (
                        <Button
                          size="xs"
                          variant="ghost"
                          onClick={() => setDeleteTarget(a)}
                          title="Delete"
                          className="text-[var(--danger)] hover:text-[var(--danger)] hover:bg-[var(--danger-bg)]"
                        >
                          <Trash2 size={12} />
                        </Button>
                      )}
                    </div>
                  </div>
                  <p className="text-xs leading-relaxed text-[var(--text-secondary)]">
                    <span className="text-[var(--text-primary)]">{a.role}</span>
                    {" — "}
                    {a.goal}
                  </p>
                  {a.tools && a.tools.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {a.tools.map((t) => (
                        <span
                          key={t}
                          className="text-[10px] px-1.5 py-0.5 rounded font-mono bg-[var(--bg-secondary)] text-[var(--text-tertiary)] border border-[var(--border)]"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}

          {learningAgents.length > 0 && (
            <div className="mt-4 rounded-xl p-3.5 bg-[var(--bg-tertiary)] border border-[var(--border)]">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-sm">🧠</span>
                <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                  Learning Stats
                </span>
              </div>
              <div className="flex gap-1.5 mb-2 flex-wrap">
                {learningAgents.map((name) => (
                  <button
                    key={name}
                    onClick={() => loadLearning(name)}
                    className={cn(
                      "text-[11px] px-2.5 py-1 rounded-md font-mono transition-colors",
                      selectedLearnAgent === name
                        ? "bg-[var(--brand)] text-white"
                        : "bg-[var(--bg-secondary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] border border-[var(--border)]",
                    )}
                  >
                    {name}
                  </button>
                ))}
              </div>
              {loadingLearn && (
                <div className="flex items-center gap-2 py-2 text-xs text-[var(--text-tertiary)]">
                  <Loader2 size={12} className="animate-spin" /> Loading…
                </div>
              )}
              {agentStats && !loadingLearn && (
                <div className="space-y-2">
                  <div className="flex gap-3 text-[11px] font-mono flex-wrap">
                    <span className="text-[var(--text-tertiary)]">
                      Tasks:{" "}
                      <b className="text-[var(--text-primary)]">
                        {agentStats.total}
                      </b>
                    </span>
                    <span className="text-[var(--text-tertiary)]">
                      Success:{" "}
                      <b className="text-[var(--success)]">
                        {agentStats.success_rate}%
                      </b>
                    </span>
                    <span className="text-[var(--text-tertiary)]">
                      Avg:{" "}
                      <b className="text-[var(--text-primary)]">
                        {agentStats.avg_elapsed}s
                      </b>
                    </span>
                    <span className="text-[var(--text-tertiary)]">
                      Tokens:{" "}
                      <b className="text-[var(--text-primary)]">
                        {agentStats.avg_tokens}
                      </b>
                    </span>
                  </div>
                  {agentMemories.length > 0 && (
                    <div className="space-y-1 max-h-40 overflow-y-auto">
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
                            onClick={() => handleDeleteMemory(m.key)}
                            className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0 p-0.5 rounded text-[var(--danger)] hover:bg-[var(--danger-bg)]"
                            title="Delete"
                          >
                            <Trash2 size={10} />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {!agentStats && !loadingLearn && selectedLearnAgent && (
                <p className="text-[11px] text-[var(--text-tertiary)]">
                  No data for {selectedLearnAgent}
                </p>
              )}
            </div>
          )}
        </div>
      </>
    );

  return inline ? (
    <div className="flex flex-col h-full">
      <header className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)] bg-[var(--bg-secondary)]">
        <div>
          <h1 className="text-base font-semibold text-[var(--text-primary)]">
            {headerLabel}
          </h1>
          <p className="text-xs text-[var(--text-secondary)] mt-0.5">
            Configure your multi-agent team
          </p>
        </div>
        {newAgentButton}
      </header>
      <div className="flex-1 overflow-y-auto px-6 py-4">{bodyContent}</div>
      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        title={`Delete agent "${deleteTarget?.display_name}"?`}
        description="This permanently removes the agent profile and its learning data."
        confirmText="Delete"
        tone="danger"
        onConfirm={() => {
          if (deleteTarget) handleDelete(deleteTarget);
        }}
      />
    </div>
  ) : (
    <>
      <Modal
        open={true}
        onOpenChange={(o) => !o && onClose()}
        title={headerLabel}
        description="Configure your multi-agent team"
        size="xl"
        footer={newAgentButton}
      >
        {bodyContent}
      </Modal>
      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        title={`Delete agent "${deleteTarget?.display_name}"?`}
        description="This permanently removes the agent profile and its learning data."
        confirmText="Delete"
        tone="danger"
        onConfirm={() => {
          if (deleteTarget) handleDelete(deleteTarget);
        }}
      />
    </>
  );
}

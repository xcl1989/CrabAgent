import { useState, useEffect, useCallback } from "react";
import {
  FolderOpen,
  Lightbulb,
  User,
  Search,
  Plus,
  Trash2,
  Pencil,
  X,
  Check,
  Brain,
  Loader2,
  ChevronDown,
} from "lucide-react";
import {
  listMemories,
  createMemory,
  updateMemory,
  deleteAgentMemory,
  getProjectMemory,
  type MemoryEntry,
  type ProjectMemoryData,
} from "../api/agents";
import { listWorkspaces, type WorkspaceInfo } from "../api/sessions";
import { Button, Input, Modal, EmptyState, toast } from "../components/ui";
import { cn } from "../lib/cn";

type MemoryTab = "project" | "agent_lesson" | "user_preference";

const TAB_LABELS: Record<MemoryTab, string> = {
  project: "\uD83D\uDCC1 Project Memory",
  agent_lesson: "\uD83E\uDD16 Agent Lessons",
  user_preference: "\uD83D\uDC64 User Preferences",
};

const TAB_TYPES: Record<MemoryTab, string> = {
  project: "",
  agent_lesson: "agent_lesson",
  user_preference: "user_preference",
};

function formatDate(iso: string): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    return `${mm}-${dd}`;
  } catch {
    return iso.slice(5, 10);
  }
}

export default function MemoryPage() {
  const [tab, setTab] = useState<MemoryTab>("project");
  const [entries, setEntries] = useState<MemoryEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [agentFilter, setAgentFilter] = useState("");

  // Project memory specific
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState("");
  const [projectMemory, setProjectMemory] = useState<ProjectMemoryData | null>(null);
  const [wsOpen, setWsOpen] = useState(false);

  // CRUD modals
  const [editingEntry, setEditingEntry] = useState<MemoryEntry | null>(null);
  const [editContent, setEditContent] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState({ key: "", content: "", category: "" });

  const fetchEntries = useCallback(async () => {
    setLoading(true);
    try {
      const type = TAB_TYPES[tab];
      const params: Record<string, string> = {};
      if (type) params.memory_type = type;
      if (tab === "project" && selectedWorkspace) params.workspace = selectedWorkspace;
      if (search) params.q = search;
      if (agentFilter && tab === "agent_lesson") params.agent_name = agentFilter;
      const items = await listMemories(params);
      setEntries(items);
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [tab, search, agentFilter, selectedWorkspace]);

  useEffect(() => {
    fetchEntries();
  }, [fetchEntries]);

  // Load workspaces and project memory
  useEffect(() => {
    (async () => {
      try {
        const wsList = await listWorkspaces();
        setWorkspaces(wsList);
        if (wsList.length > 0) {
          const sorted = [...wsList].sort((a, b) => {
            if (!a.last_active) return 1;
            if (!b.last_active) return -1;
            return b.last_active.localeCompare(a.last_active);
          });
          setSelectedWorkspace(sorted[0].workspace);
          const pm = await getProjectMemory(sorted[0].workspace);
          if (pm) setProjectMemory(pm);
        }
      } catch {}
    })();
  }, []);

  const handleSwitchWorkspace = async (ws: string) => {
    setSelectedWorkspace(ws);
    setWsOpen(false);
    try {
      const pm = await getProjectMemory(ws);
      if (pm) setProjectMemory(pm);
    } catch {}
  };

  const handleDelete = async (entry: MemoryEntry) => {
    try {
      await deleteAgentMemory(entry.key);
      toast.success("Memory deleted");
      fetchEntries();
    } catch {
      toast.error("Failed to delete");
    }
  };

  const handleEdit = async () => {
    if (!editingEntry) return;
    try {
      await updateMemory(editingEntry.key, editContent);
      toast.success("Memory updated");
      setEditingEntry(null);
      fetchEntries();
    } catch {
      toast.error("Failed to update");
    }
  };

  const handleCreate = async () => {
    if (!createForm.key || !createForm.content) {
      toast.error("Key and content are required");
      return;
    }
    try {
      await createMemory({
        memory_type: TAB_TYPES[tab] || "agent_lesson",
        agent_name: tab === "user_preference" ? "" : agentFilter || "default",
        category: createForm.category || "general",
        key: createForm.key,
        content: createForm.content,
        importance: 0.5,
      });
      toast.success("Memory created");
      setShowCreate(false);
      setCreateForm({ key: "", content: "", category: "" });
      fetchEntries();
    } catch {
      toast.error("Failed to create");
    }
  };

  // Collect unique agent names for filter
  const agentNames = [...new Set(entries.map((e) => e.agent_name).filter(Boolean))].sort();

  return (
    <div className="h-full flex flex-col overflow-hidden bg-[var(--bg-primary)]">
      {/* Header */}
      <div className="flex items-center gap-4 px-6 h-12 border-b border-[var(--border)] bg-[var(--bg-secondary)]">
        <Brain size={15} className="text-[var(--text-tertiary)]" />
        <span className="text-sm font-semibold tracking-wide text-[var(--text-primary)] font-mono">
          MEMORY
        </span>
        <div className="flex-1" />
        <span className="text-xs text-[var(--text-tertiary)]">
          {entries.length} entries
        </span>
      </div>

      {/* Tabs */}
      <div className="px-5 pt-5">
        <div className="flex items-center gap-1 mb-4 border-b border-[var(--border)] pb-2">
          {(Object.keys(TAB_LABELS) as MemoryTab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-sm font-medium transition-all relative",
                tab === t
                  ? "text-[var(--text-primary)] bg-[var(--bg-tertiary)]"
                  : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]/60",
              )}
            >
              {TAB_LABELS[t]}
              {tab === t && (
                <span className="absolute -bottom-[10px] left-1/2 -translate-x-1/2 w-1 h-1 rounded-full bg-[var(--brand)]" />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Project Memory Tab: Workspace selector + tech stack (fixed) */}
      {tab === "project" && projectMemory && (
        <div className="px-5 pb-3">
          {workspaces.length > 1 && (
            <div className="relative mb-3">
              <button
                onClick={() => setWsOpen((o) => !o)}
                className="flex items-center gap-2 w-full max-w-xs px-3 py-1.5 rounded-lg text-xs text-left border border-[var(--border)] bg-[var(--bg-tertiary)] text-[var(--text-primary)] hover:border-[var(--border-strong)] transition-colors"
              >
                <FolderOpen size={12} className="text-[var(--text-tertiary)] shrink-0" />
                <span className="flex-1 truncate">
                  {selectedWorkspace
                    ? selectedWorkspace.split("/").slice(-2).join("/")
                    : "Select workspace"}
                </span>
                <ChevronDown
                  size={12}
                  className={cn("text-[var(--text-tertiary)] transition-transform", wsOpen && "rotate-180")}
                />
              </button>
              {wsOpen && (
                <div className="absolute top-full left-0 z-50 mt-1 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] shadow-[var(--shadow-lg)] max-h-48 overflow-auto max-w-xs">
                  {workspaces.map((ws) => (
                    <button
                      key={ws.workspace}
                      onClick={() => handleSwitchWorkspace(ws.workspace)}
                      className={cn(
                        "w-full flex items-center gap-2 px-3 py-2 text-xs text-left transition-colors",
                        ws.workspace === selectedWorkspace
                          ? "bg-[var(--brand-bg)] text-[var(--brand)]"
                          : "text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
                      )}
                    >
                      <span className="flex-1 truncate">
                        {ws.workspace.split("/").slice(-2).join("/")}
                      </span>
                      <span className="text-[10px] text-[var(--text-tertiary)] shrink-0">
                        {ws.session_count}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {(projectMemory.tech_stack?.length ?? 0) > 0 && (
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs text-[var(--text-tertiary)] font-medium">Tech Stack:</span>
              <div className="flex flex-wrap gap-1.5">
                {projectMemory.tech_stack!.map((t) => (
                  <span key={t} className="px-2 py-0.5 rounded-md text-[11px] font-mono font-medium bg-[var(--bg-tertiary)] text-[var(--text-secondary)]">
                    {t}
                  </span>
                ))}
              </div>
            </div>
          )}
          {projectMemory.last_active && (
            <div className="text-xs text-[var(--text-tertiary)] mb-2">
              Last active: {projectMemory.last_active}
            </div>
          )}
        </div>
      )}

      {/* Search + Filter bar (fixed) */}
      <div className="flex items-center gap-2 px-5 pb-3">
        <div className="relative flex-1 max-w-sm">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search memories..."
            className="w-full h-8 pl-8 pr-3 rounded-lg text-xs border border-[var(--border)] bg-[var(--bg-tertiary)] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none focus:border-[var(--brand)] transition-colors"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
            >
              <X size={12} />
            </button>
          )}
        </div>

        {tab === "agent_lesson" && agentNames.length > 0 && (
          <select
            value={agentFilter}
            onChange={(e) => setAgentFilter(e.target.value)}
            className="h-8 px-2 rounded-lg text-xs border border-[var(--border)] bg-[var(--bg-tertiary)] text-[var(--text-primary)] outline-none focus:border-[var(--brand)]"
          >
            <option value="">All agents</option>
            {agentNames.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        )}

        <Button variant="ghost" size="xs" onClick={() => setShowCreate(true)}>
          <Plus size={13} /> Add
        </Button>
      </div>

      {/* Memory list (scrollable) */}
      <div className="flex-1 overflow-y-auto px-5 pb-5">

        {/* Memory list */}
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 size={20} className="animate-spin text-[var(--text-tertiary)]" />
          </div>
        ) : entries.length === 0 ? (
          <EmptyState
            icon={<Brain size={28} className="text-[var(--text-tertiary)]" />}
            title={search ? "No matching memories" : "No memories yet"}
            description={
              search
                ? "Try a different search term"
                : tab === "project"
                  ? "Start working in a project to build memory"
                  : tab === "agent_lesson"
                    ? "Agent lessons appear automatically after tasks"
                    : "User preferences are learned over time"
            }
          />
        ) : (
          <div className="space-y-1.5">
            {entries.map((entry) => (
              <div
                key={entry.key}
                className="flex items-start gap-3 px-4 py-3 rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] group hover:border-[var(--border-strong)] transition-colors"
              >
                {/* Category badge */}
                <span className={cn(
                  "text-[10px] px-1.5 py-0.5 rounded shrink-0 font-mono mt-0.5",
                  entry.memory_type === "user_preference"
                    ? "bg-purple-500/15 text-purple-400"
                    : entry.memory_type === "agent_lesson"
                      ? "bg-emerald-500/15 text-emerald-400"
                      : "bg-blue-500/15 text-blue-400",
                )}>
                  {entry.category}
                </span>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="text-xs leading-relaxed text-[var(--text-secondary)] whitespace-pre-wrap">
                    {entry.content}
                  </div>
                  <div className="flex items-center gap-2 mt-1">
                    {entry.agent_name && (
                      <span className="text-[10px] font-mono text-[var(--text-tertiary)]">
                        @{entry.agent_name}
                      </span>
                    )}
                    <span className="text-[10px] text-[var(--text-tertiary)]">
                      {formatDate(entry.updated_at)}
                    </span>
                    {entry.confidence > 0 && (
                      <span className="text-[10px] text-[var(--text-tertiary)]">
                        {Math.round(entry.confidence * 100)}%
                      </span>
                    )}
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    onClick={() => {
                      setEditingEntry(entry);
                      setEditContent(entry.content);
                    }}
                    className="p-1 rounded text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]"
                    title="Edit"
                  >
                    <Pencil size={12} />
                  </button>
                  <button
                    onClick={() => handleDelete(entry)}
                    className="p-1 rounded text-[var(--danger)] hover:bg-[var(--danger-bg)]"
                    title="Delete"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Edit modal */}
      <Modal
        open={!!editingEntry}
        onOpenChange={(o) => !o && setEditingEntry(null)}
        title="Edit Memory"
        size="md"
        footer={
          <div className="flex gap-2">
            <Button variant="brand" onClick={handleEdit}>
              <Check size={13} /> Save
            </Button>
            <Button variant="ghost" onClick={() => setEditingEntry(null)}>
              Cancel
            </Button>
          </div>
        }
      >
        {editingEntry && (
          <div className="space-y-3">
            <div className="text-xs text-[var(--text-tertiary)]">
              <span className="font-medium">Key:</span> {editingEntry.key}
            </div>
            <textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              className="w-full min-h-[120px] p-3 rounded-lg text-xs border border-[var(--border)] bg-[var(--bg-tertiary)] text-[var(--text-primary)] outline-none focus:border-[var(--brand)] resize-y transition-colors font-mono leading-relaxed"
            />
          </div>
        )}
      </Modal>

      {/* Create modal */}
      <Modal
        open={showCreate}
        onOpenChange={(o) => !o && setShowCreate(false)}
        title="Add Memory"
        size="md"
        footer={
          <div className="flex gap-2">
            <Button variant="brand" onClick={handleCreate}>
              <Plus size={13} /> Create
            </Button>
            <Button variant="ghost" onClick={() => setShowCreate(false)}>
              Cancel
            </Button>
          </div>
        }
      >
        <div className="space-y-3">
          <Input
            label="Key"
            value={createForm.key}
            onChange={(e) => setCreateForm({ ...createForm, key: e.target.value })}
            placeholder="e.g. lesson:my_tip"
          />
          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)] mb-1">
              Category
            </label>
            <input
              value={createForm.category}
              onChange={(e) => setCreateForm({ ...createForm, category: e.target.value })}
              placeholder="e.g. tech_stack, architecture, user_preference"
              className="w-full h-8 px-3 rounded-lg text-xs border border-[var(--border)] bg-[var(--bg-tertiary)] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none focus:border-[var(--brand)] transition-colors"
            />
          </div>
          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)] mb-1">
              Content
            </label>
            <textarea
              value={createForm.content}
              onChange={(e) => setCreateForm({ ...createForm, content: e.target.value })}
              className="w-full min-h-[100px] p-3 rounded-lg text-xs border border-[var(--border)] bg-[var(--bg-tertiary)] text-[var(--text-primary)] outline-none focus:border-[var(--brand)] resize-y transition-colors font-mono leading-relaxed"
              placeholder="Memory content..."
            />
          </div>
        </div>
      </Modal>
    </div>
  );
}

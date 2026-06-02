import { useState, useEffect } from "react";
import { Plus, Play, Pencil, Trash2, Clock } from "lucide-react";
import {
  ScheduledTask,
  listScheduledTasks,
  createScheduledTask,
  updateScheduledTask,
  deleteScheduledTask,
  runScheduledTask,
  type CreateScheduledTaskRequest,
} from "../api/scheduledTasks";
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

interface Props {
  onClose: () => void;
  onSwitchSession: (sessionId: string) => void;
}

function cronToHuman(expr: string): string {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return expr;
  const [min, hour, day, month, week] = parts;
  if (min.startsWith("*/")) return `Every ${min.slice(2)} min`;
  if (hour === "*" && day === "*" && month === "*" && week === "*")
    return `Hourly at :${min.padStart(2, "0")}`;
  if (day === "*" && month === "*" && week === "*")
    return `Daily at ${hour}:${min.padStart(2, "0")}`;
  if (day === "*" && month === "*" && week !== "*") {
    const days: Record<string, string> = {
      "0": "Sun",
      "1": "Mon",
      "2": "Tue",
      "3": "Wed",
      "4": "Thu",
      "5": "Fri",
      "6": "Sat",
    };
    const wdays = week
      .split(",")
      .map((d) => days[d] || d)
      .join(", ");
    return `Every ${wdays} at ${hour}:${min.padStart(2, "0")}`;
  }
  if (hour !== "*" && day !== "*" && month !== "*")
    return `${month}/${day} ${hour}:${min.padStart(2, "0")}`;
  return expr;
}

const PRESETS: { label: string; cron: string }[] = [
  { label: "Every 30 min", cron: "*/30 * * * *" },
  { label: "Hourly", cron: "0 * * * *" },
  { label: "Daily 9am", cron: "0 9 * * *" },
  { label: "Weekdays 9am", cron: "0 9 * * 1-5" },
  { label: "Weekly Mon", cron: "0 9 * * 1" },
  { label: "Monthly 1st", cron: "0 9 1 * *" },
];

export function ScheduledTaskPanel({ onClose, onSwitchSession }: Props) {
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<CreateScheduledTaskRequest>({
    name: "",
    prompt: "",
    cron_expression: "0 9 * * *",
    model: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [acting, setActing] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null);

  const fetchTasks = async () => {
    try {
      setTasks(await listScheduledTasks());
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    fetchTasks();
  }, []);

  const resetForm = () => {
    setForm({ name: "", prompt: "", cron_expression: "0 9 * * *", model: "" });
    setEditingId(null);
    setShowForm(false);
    setError("");
  };

  const handleSubmit = async () => {
    if (!form.name.trim() || !form.prompt.trim() || !form.cron_expression.trim()) {
      setError("All fields are required");
      return;
    }
    const parts = form.cron_expression.trim().split(/\s+/);
    if (parts.length !== 5) {
      setError("Cron expression requires 5 fields: min hour day month weekday");
      return;
    }
    setLoading(true);
    setError("");
    try {
      if (editingId) {
        await updateScheduledTask(editingId, form);
        toast.success("Task updated");
      } else {
        await createScheduledTask(form);
        toast.success("Task created");
      }
      await fetchTasks();
      resetForm();
    } catch (e: any) {
      setError(e?.message || e?.detail || "Operation failed");
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: number) => {
    setActing(id);
    try {
      await deleteScheduledTask(id);
      toast.success("Task deleted");
      await fetchTasks();
    } catch {
      toast.error("Delete failed");
    } finally {
      setActing(null);
      setDeleteTarget(null);
    }
  };

  const handleToggle = async (t: ScheduledTask) => {
    setActing(t.id);
    try {
      await updateScheduledTask(t.id, { enabled: !t.enabled });
      await fetchTasks();
    } catch {
      /* ignore */
    } finally {
      setActing(null);
    }
  };

  const handleRun = async (id: number) => {
    setActing(id);
    try {
      await runScheduledTask(id);
      toast.success("Task triggered");
    } catch (e: any) {
      toast.error(e?.message || "Run failed");
    } finally {
      setActing(null);
    }
  };

  const startEdit = (t: ScheduledTask) => {
    setEditingId(t.id);
    setForm({
      name: t.name,
      prompt: t.prompt,
      cron_expression: t.cron_expression,
      model: t.model || "",
    });
    setShowForm(true);
    setError("");
  };

  return (
    <>
      <Modal
        open={true}
        onOpenChange={(o) => !o && onClose()}
        title="Scheduled Tasks"
        description="Run prompts on a recurring schedule"
        size="lg"
        footer={
          !showForm ? (
            <Button
              variant="brand"
              onClick={() => {
                resetForm();
                setShowForm(true);
              }}
            >
              <Plus size={14} /> New Task
            </Button>
          ) : (
            <>
              <Button variant="ghost" onClick={resetForm}>
                Cancel
              </Button>
              <Button variant="brand" loading={loading} onClick={handleSubmit}>
                {editingId ? "Save Changes" : "Create Task"}
              </Button>
            </>
          )
        }
      >
        {error && (
          <div className="mb-3 px-3 py-2 rounded-lg bg-[var(--danger-bg)] border border-[var(--danger-border)] text-xs text-[var(--danger)]">
            {error}
          </div>
        )}

        {showForm ? (
          <div className="space-y-3">
            <Input
              label="Name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. Morning news summary"
            />
            <Textarea
              label="Prompt"
              value={form.prompt}
              onChange={(e) => setForm({ ...form, prompt: e.target.value })}
              rows={3}
              placeholder="The question to send to the AI"
            />
            <div>
              <Input
                label="Cron Expression"
                value={form.cron_expression}
                onChange={(e) =>
                  setForm({ ...form, cron_expression: e.target.value })
                }
                placeholder="0 9 * * *"
                hint={`→ ${cronToHuman(form.cron_expression)}`}
              />
              <div className="flex flex-wrap gap-1 mt-2">
                {PRESETS.map((p) => (
                  <button
                    key={p.cron}
                    onClick={() =>
                      setForm({ ...form, cron_expression: p.cron })
                    }
                    className={cn(
                      "text-[10px] px-2 py-1 rounded-md transition-colors",
                      form.cron_expression === p.cron
                        ? "bg-[var(--brand-bg)] text-[var(--brand)] border border-[var(--brand-border)]"
                        : "bg-[var(--bg-tertiary)] text-[var(--text-secondary)] border border-[var(--border)] hover:text-[var(--text-primary)]",
                    )}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
            <Input
              label="Model (optional)"
              value={form.model}
              onChange={(e) => setForm({ ...form, model: e.target.value })}
              placeholder="Leave empty to use default"
            />
          </div>
        ) : tasks.length === 0 ? (
          <EmptyState
            icon={<Clock size={32} />}
            title="No scheduled tasks"
            description="Create recurring prompts that run automatically."
            action={
              <Button
                variant="brand"
                size="sm"
                onClick={() => {
                  resetForm();
                  setShowForm(true);
                }}
              >
                <Plus size={14} /> New Task
              </Button>
            }
          />
        ) : (
          <div className="space-y-2">
            {tasks.map((t) => (
              <div
                key={t.id}
                className="p-3 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border)] hover:border-[var(--border-strong)] transition-colors"
              >
                <div className="flex items-center justify-between gap-2 mb-1">
                  <span className="text-sm font-semibold text-[var(--text-primary)] truncate">
                    {t.name}
                  </span>
                  <button
                    onClick={() => handleToggle(t)}
                    disabled={acting === t.id}
                    className={cn(
                      "shrink-0 text-[10px] px-2 py-0.5 rounded-full font-medium border transition-colors",
                      t.enabled
                        ? "bg-[var(--success-bg)] text-[var(--success)] border-[var(--success-border)] hover:bg-[var(--success)] hover:text-white"
                        : "bg-[var(--bg-elevated)] text-[var(--text-tertiary)] border-[var(--border)] hover:text-[var(--text-secondary)]",
                    )}
                  >
                    {t.enabled ? "Active" : "Paused"}
                  </button>
                </div>
                <div className="text-xs text-[var(--text-secondary)] mb-1 flex items-center gap-1.5 flex-wrap">
                  <span className="font-mono text-[var(--accent)]">
                    {t.cron_expression}
                  </span>
                  <span className="text-[var(--text-tertiary)]">·</span>
                  <span>{cronToHuman(t.cron_expression)}</span>
                  {t.model && (
                    <>
                      <span className="text-[var(--text-tertiary)]">·</span>
                      <span className="font-mono text-[10px]">{t.model}</span>
                    </>
                  )}
                </div>
                <div className="text-xs text-[var(--text-tertiary)] mb-2 truncate">
                  {t.prompt}
                </div>
                {t.last_run_at && (
                  <div className="text-[10px] mb-2 text-[var(--text-tertiary)] font-mono">
                    Last: {new Date(t.last_run_at).toLocaleString()}
                    {t.last_status === "error" && (
                      <span className="text-[var(--danger)] ml-1">(failed)</span>
                    )}
                    {t.last_status === "success" && (
                      <span className="text-[var(--success)] ml-1">(ok)</span>
                    )}
                  </div>
                )}
                <div className="flex items-center gap-1.5">
                  <Button
                    size="xs"
                    variant="primary"
                    onClick={() => handleRun(t.id)}
                    loading={acting === t.id}
                  >
                    <Play size={11} /> Run
                  </Button>
                  {t.last_conversation_id && (
                    <Button
                      size="xs"
                      variant="ghost"
                      onClick={() => {
                        onSwitchSession(t.last_conversation_id);
                        onClose();
                      }}
                    >
                      View Result
                    </Button>
                  )}
                  <Button
                    size="xs"
                    variant="ghost"
                    onClick={() => startEdit(t)}
                  >
                    <Pencil size={11} /> Edit
                  </Button>
                  <Button
                    size="xs"
                    variant="ghost"
                    onClick={() => setDeleteTarget(t.id)}
                    className="text-[var(--danger)] hover:text-[var(--danger)] hover:bg-[var(--danger-bg)]"
                  >
                    <Trash2 size={11} />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Modal>

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        title="Delete this task?"
        description="This will permanently remove the scheduled task."
        confirmText="Delete"
        tone="danger"
        onConfirm={() => {
          if (deleteTarget != null) handleDelete(deleteTarget);
        }}
      />
    </>
  );
}

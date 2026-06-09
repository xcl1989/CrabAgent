import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation();
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
      setError(t("scheduledTask.allFieldsRequired"));
      return;
    }
    const parts = form.cron_expression.trim().split(/\s+/);
    if (parts.length !== 5) {
      setError(t("scheduledTask.cronFieldsRequired"));
      return;
    }
    setLoading(true);
    setError("");
    try {
      if (editingId) {
        await updateScheduledTask(editingId, form);
        toast.success(t("scheduledTask.taskUpdated"));
      } else {
        await createScheduledTask(form);
        toast.success(t("scheduledTask.taskCreated"));
      }
      await fetchTasks();
      resetForm();
    } catch (e: any) {
      setError(e?.message || e?.detail || t("scheduledTask.operationFailed"));
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: number) => {
    setActing(id);
    try {
      await deleteScheduledTask(id);
      toast.success(t("scheduledTask.taskDeleted"));
      await fetchTasks();
    } catch {
      toast.error(t("scheduledTask.operationFailed"));
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
      toast.success(t("scheduledTask.taskCreated"));
    } catch (e: any) {
      toast.error(e?.message || t("scheduledTask.operationFailed"));
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
        title={t("scheduledTask.title")}
        description={t("scheduledTask.title")}
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
              <Plus size={14} /> {t("scheduledTask.newTask")}
            </Button>
          ) : (
            <>
              <Button variant="ghost" onClick={resetForm}>
                {t("common.cancel")}
              </Button>
              <Button variant="brand" loading={loading} onClick={handleSubmit}>
                {editingId ? t("scheduledTask.saveChanges") : t("scheduledTask.createTask")}
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
              label={t("scheduledTask.taskName")}
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder={t("scheduledTask.namePlaceholder2")}
            />
            <Textarea
              label={t("scheduledTask.taskQuestion")}
              value={form.prompt}
              onChange={(e) => setForm({ ...form, prompt: e.target.value })}
              rows={3}
              placeholder={t("scheduledTask.questionPlaceholder")}
            />
            <div>
              <Input
                label={t("scheduledTask.cronExpression")}
                value={form.cron_expression}
                onChange={(e) =>
                  setForm({ ...form, cron_expression: e.target.value })
                }
                placeholder={t("scheduledTask.cronPlaceholder2")}
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
              label={t("scheduledTask.model")}
              value={form.model}
              onChange={(e) => setForm({ ...form, model: e.target.value })}
              placeholder={t("scheduledTask.cronPlaceholder")}
            />
          </div>
        ) : tasks.length === 0 ? (
          <EmptyState
            icon={<Clock size={32} />}
            title={t("scheduledTask.noTasks")}
            description={t("scheduledTask.title")}
            action={
              <Button
                variant="brand"
                size="sm"
                onClick={() => {
                  resetForm();
                  setShowForm(true);
                }}
              >
                <Plus size={14} /> {t("scheduledTask.newTask")}
              </Button>
            }
          />
        ) : (
          <div className="space-y-2">
            {tasks.map((task) => (
              <div
                key={task.id}
                className="p-3 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border)] hover:border-[var(--border-strong)] transition-colors"
              >
                <div className="flex items-center justify-between gap-2 mb-1">
                  <span className="text-sm font-semibold text-[var(--text-primary)] truncate">
                    {task.name}
                  </span>
                  <button
                    onClick={() => handleToggle(task)}
                    disabled={acting === task.id}
                    className={cn(
                      "shrink-0 text-[10px] px-2 py-0.5 rounded-full font-medium border transition-colors",
                      task.enabled
                        ? "bg-[var(--success-bg)] text-[var(--success)] border-[var(--success-border)] hover:bg-[var(--success)] hover:text-white"
                        : "bg-[var(--bg-elevated)] text-[var(--text-tertiary)] border-[var(--border)] hover:text-[var(--text-secondary)]",
                    )}
                  >
                    {task.enabled ? t("scheduledTask.active") : t("scheduledTask.paused")}
                  </button>
                </div>
                <div className="text-xs text-[var(--text-secondary)] mb-1 flex items-center gap-1.5 flex-wrap">
                  <span className="font-mono text-[var(--accent)]">
                    {task.cron_expression}
                  </span>
                  <span className="text-[var(--text-tertiary)]">·</span>
                  <span>{cronToHuman(task.cron_expression)}</span>
                  {task.model && (
                    <>
                      <span className="text-[var(--text-tertiary)]">·</span>
                      <span className="font-mono text-[10px]">{task.model}</span>
                    </>
                  )}
                </div>
                <div className="text-xs text-[var(--text-tertiary)] mb-2 truncate">
                  {task.prompt}
                </div>
                {task.last_run_at && (
                  <div className="text-[10px] mb-2 text-[var(--text-tertiary)] font-mono">
                    Last: {new Date(task.last_run_at).toLocaleString()}
                    {task.last_status === "error" && (
                      <span className="text-[var(--danger)] ml-1">(failed)</span>
                    )}
                    {task.last_status === "success" && (
                      <span className="text-[var(--success)] ml-1">(ok)</span>
                    )}
                  </div>
                )}
                <div className="flex items-center gap-1.5">
                  <Button
                    size="xs"
                    variant="primary"
                    onClick={() => handleRun(task.id)}
                    loading={acting === task.id}
                  >
                    <Play size={11} /> Run
                  </Button>
                  {task.last_conversation_id && (
                    <Button
                      size="xs"
                      variant="ghost"
                      onClick={() => {
                        onSwitchSession(task.last_conversation_id);
                        onClose();
                      }}
                    >
                      View Result
                    </Button>
                  )}
                  <Button
                    size="xs"
                    variant="ghost"
                    onClick={() => startEdit(task)}
                  >
                    <Pencil size={11} /> Edit
                  </Button>
                  <Button
                    size="xs"
                    variant="ghost"
                    onClick={() => setDeleteTarget(task.id)}
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
        title={t("scheduledTask.deleteConfirm")}
        description=""
        confirmText={t("common.delete")}
        tone="danger"
        onConfirm={() => {
          if (deleteTarget != null) handleDelete(deleteTarget);
        }}
      />
    </>
  );
}

import { useState, useEffect } from "react";
import { ScheduledTask, listScheduledTasks, createScheduledTask, updateScheduledTask, deleteScheduledTask, runScheduledTask, CreateScheduledTaskRequest } from "../api/scheduledTasks";

interface Props {
  onClose: () => void;
  onSwitchSession: (sessionId: string) => void;
}

function cronToHuman(expr: string): string {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return expr;
  const [min, hour, day, month, week] = parts;
  if (min.startsWith("*/")) return `Every ${min.slice(2)} min`;
  if (hour === "*" && day === "*" && month === "*" && week === "*") return `Daily at ${hour}:${min.padStart(2, "0")}`;
  if (day === "*" && month === "*" && week !== "*") {
    const days: Record<string, string> = { "0": "Sun", "1": "Mon", "2": "Tue", "3": "Wed", "4": "Thu", "5": "Fri", "6": "Sat" };
    const wdays = week.split(",").map((d) => days[d] || d).join(", ");
    return `Every ${wdays} at ${hour}:${min.padStart(2, "0")}`;
  }
  if (hour !== "*" && day !== "*" && month !== "*") return `${month}/${day} ${hour}:${min.padStart(2, "0")}`;
  return expr;
}

export function ScheduledTaskPanel({ onClose, onSwitchSession }: Props) {
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<CreateScheduledTaskRequest>({ name: "", prompt: "", cron_expression: "0 9 * * *", model: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [acting, setActing] = useState<number | null>(null);

  const fetchTasks = async () => {
    try {
      const list = await listScheduledTasks();
      setTasks(list);
    } catch { /* ignore */ }
  };

  useEffect(() => { fetchTasks(); }, []);

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
      } else {
        await createScheduledTask(form);
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
    if (!confirm("Delete this task?")) return;
    setActing(id);
    try {
      await deleteScheduledTask(id);
      await fetchTasks();
    } catch (e: any) {
      setError(e?.message || "Delete failed");
    } finally {
      setActing(null);
    }
  };

  const handleToggle = async (t: ScheduledTask) => {
    setActing(t.id);
    try {
      await updateScheduledTask(t.id, { enabled: !t.enabled });
      await fetchTasks();
    } catch { /* ignore */ }
    finally { setActing(null); }
  };

  const handleRun = async (id: number) => {
    setActing(id);
    try {
      await runScheduledTask(id);
    } catch (e: any) {
      setError(e?.message || "Run failed");
    } finally {
      setActing(null);
    }
  };

  const startEdit = (t: ScheduledTask) => {
    setEditingId(t.id);
    setForm({ name: t.name, prompt: t.prompt, cron_expression: t.cron_expression, model: t.model || "" });
    setShowForm(true);
    setError("");
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.6)" }}>
      <div className="w-full max-w-lg rounded-xl p-6 max-h-[85vh] overflow-y-auto" style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>Scheduled Tasks</h2>
          <button onClick={onClose} className="text-xl leading-none" style={{ color: "var(--text-secondary)" }}>✕</button>
        </div>

        {error && (
          <div className="mb-3 px-3 py-2 rounded text-xs" style={{ background: "var(--danger-bg)", color: "var(--danger)", border: "1px solid var(--danger-border)" }}>{error}</div>
        )}

        {!showForm ? (
          <>
            <button
              onClick={() => { resetForm(); setShowForm(true); }}
              className="w-full mb-4 py-2 rounded-lg text-sm font-medium transition-opacity hover:opacity-80"
              style={{ background: "var(--accent)", color: "var(--text-on-accent)" }}
            >
              + New Task
            </button>
            {tasks.length === 0 ? (
              <div className="text-center text-sm py-6" style={{ color: "var(--text-secondary)" }}>No scheduled tasks</div>
            ) : (
              tasks.map((t) => (
                <div key={t.id} className="mb-3 p-3 rounded-lg" style={{ background: "var(--bg-primary)", border: "1px solid var(--border)" }}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{t.name}</span>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => handleToggle(t)} disabled={acting === t.id}
                        className="text-[10px] px-2 py-0.5 rounded"
                        style={{ background: t.enabled ? "var(--success-bg)" : "var(--bg-elevated)", color: "var(--text-on-accent)" }}
                      >
                        {t.enabled ? "Active" : "Paused"}
                      </button>
                    </div>
                  </div>
                  <div className="text-xs mb-1" style={{ color: "var(--text-secondary)" }}>
                    <span className="font-mono">{t.cron_expression}</span>
                    <span className="mx-1">·</span>
                    <span>{cronToHuman(t.cron_expression)}</span>
                    {t.model && <span className="ml-1">· {t.model}</span>}
                  </div>
                  <div className="text-xs mb-2 truncate" style={{ color: "var(--text-secondary)" }}>{t.prompt}</div>
                  {t.last_run_at && (
                    <div className="text-[10px] mb-2" style={{ color: "var(--text-secondary)" }}>
                      Last: {new Date(t.last_run_at).toLocaleString()}
                      {t.last_status === "error" && <span style={{ color: "var(--danger)" }}> (failed)</span>}
                      {t.last_status === "success" && <span style={{ color: "var(--success)" }}> (success)</span>}
                    </div>
                  )}
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleRun(t.id)} disabled={acting === t.id}
                      className="text-[10px] px-2 py-0.5 rounded transition-opacity hover:opacity-80"
                      style={{ background: "var(--accent)", color: "var(--text-on-accent)" }}
                    >
                      {acting === t.id ? "..." : "▶ Run Now"}
                    </button>
                    {t.last_conversation_id && (
                      <button
                        onClick={() => { onSwitchSession(t.last_conversation_id); onClose(); }}
                        className="text-[10px] px-2 py-0.5 rounded transition-opacity hover:opacity-80"
                        style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)" }}
                      >
                        View Result
                      </button>
                    )}
                    <button
                      onClick={() => startEdit(t)}
                      className="text-[10px] px-2 py-0.5 rounded transition-opacity hover:opacity-80"
                      style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)" }}
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleDelete(t.id)} disabled={acting === t.id}
                      className="text-[10px] px-2 py-0.5 rounded transition-opacity hover:opacity-80"
                      style={{ background: "var(--danger-bg)", color: "var(--danger)" }}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))
            )}
          </>
        ) : (
          <div>
            <label className="block text-xs font-medium mb-1" style={{ color: "var(--text-primary)" }}>Name</label>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="w-full mb-3 px-3 py-2 rounded-lg text-sm outline-none" style={{ background: "var(--bg-primary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              placeholder="e.g. Morning news summary" />

            <label className="block text-xs font-medium mb-1" style={{ color: "var(--text-primary)" }}>Prompt</label>
            <textarea value={form.prompt} onChange={(e) => setForm({ ...form, prompt: e.target.value })}
              className="w-full mb-3 px-3 py-2 rounded-lg text-sm outline-none resize-none" rows={3}
              style={{ background: "var(--bg-primary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              placeholder="The question to send to the AI" />

            <label className="block text-xs font-medium mb-1" style={{ color: "var(--text-primary)" }}>Cron Expression (min hour day month weekday)</label>
            <input value={form.cron_expression} onChange={(e) => setForm({ ...form, cron_expression: e.target.value })}
              className="w-full mb-1 px-3 py-2 rounded-lg text-sm font-mono outline-none" style={{ background: "var(--bg-primary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              placeholder="0 9 * * *" />
            {form.cron_expression && <div className="text-[10px] mb-3" style={{ color: "var(--text-secondary)" }}>→ {cronToHuman(form.cron_expression)}</div>}

            <label className="block text-xs font-medium mb-1" style={{ color: "var(--text-primary)" }}>Model (optional)</label>
            <input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })}
              className="w-full mb-4 px-3 py-2 rounded-lg text-sm outline-none" style={{ background: "var(--bg-primary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              placeholder="Leave empty to use default model" />

            <div className="flex items-center gap-2">
              <button
                onClick={handleSubmit} disabled={loading}
                className="flex-1 py-2 rounded-lg text-sm font-medium transition-opacity hover:opacity-80"
                style={{ background: "var(--accent)", color: "var(--text-on-accent)" }}
              >
                {loading ? "..." : editingId ? "Save Changes" : "Create Task"}
              </button>
              <button
                onClick={resetForm}
                className="flex-1 py-2 rounded-lg text-sm transition-opacity hover:opacity-80"
                style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)" }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

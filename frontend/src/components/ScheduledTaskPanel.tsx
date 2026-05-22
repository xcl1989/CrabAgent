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
  if (min.startsWith("*/")) return `每${min.slice(2)}分钟`;
  if (hour === "*" && day === "*" && month === "*" && week === "*") return `每天 ${hour}:${min.padStart(2, "0")}`;
  if (day === "*" && month === "*" && week !== "*") {
    const days: Record<string, string> = { "0": "日", "1": "一", "2": "二", "3": "三", "4": "四", "5": "五", "6": "六" };
    const wdays = week.split(",").map((d) => days[d] || d).join("、");
    return `每周${wdays} ${hour}:${min.padStart(2, "0")}`;
  }
  if (hour !== "*" && day !== "*" && month !== "*") return `${month}月${day}日 ${hour}:${min.padStart(2, "0")}`;
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
      setError("所有字段必填");
      return;
    }
    const parts = form.cron_expression.trim().split(/\s+/);
    if (parts.length !== 5) {
      setError("cron 表达式需要5个字段（分 时 日 月 周），用空格分隔");
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
      setError(e?.message || e?.detail || "操作失败");
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("确定删除此任务？")) return;
    setActing(id);
    try {
      await deleteScheduledTask(id);
      await fetchTasks();
    } catch (e: any) {
      setError(e?.message || "删除失败");
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
      setError(e?.message || "执行失败");
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
          <h2 className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>定时任务</h2>
          <button onClick={onClose} className="text-xl leading-none" style={{ color: "var(--text-secondary)" }}>✕</button>
        </div>

        {error && (
          <div className="mb-3 px-3 py-2 rounded text-xs" style={{ background: "#2d1215", color: "#fca5a5", border: "1px solid #5c1d22" }}>{error}</div>
        )}

        {!showForm ? (
          <>
            <button
              onClick={() => { resetForm(); setShowForm(true); }}
              className="w-full mb-4 py-2 rounded-lg text-sm font-medium transition-opacity hover:opacity-80"
              style={{ background: "var(--accent)", color: "#fff" }}
            >
              + 新建任务
            </button>
            {tasks.length === 0 ? (
              <div className="text-center text-sm py-6" style={{ color: "var(--text-secondary)" }}>暂无定时任务</div>
            ) : (
              tasks.map((t) => (
                <div key={t.id} className="mb-3 p-3 rounded-lg" style={{ background: "var(--bg-primary)", border: "1px solid var(--border)" }}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{t.name}</span>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => handleToggle(t)} disabled={acting === t.id}
                        className="text-[10px] px-2 py-0.5 rounded"
                        style={{ background: t.enabled ? "#065f46" : "#4b5563", color: "#fff" }}
                      >
                        {t.enabled ? "运行中" : "已暂停"}
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
                      上次: {new Date(t.last_run_at).toLocaleString("zh-CN")}
                      {t.last_status === "error" && <span style={{ color: "#fca5a5" }}> (失败)</span>}
                      {t.last_status === "success" && <span style={{ color: "#34d399" }}> (成功)</span>}
                    </div>
                  )}
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleRun(t.id)} disabled={acting === t.id}
                      className="text-[10px] px-2 py-0.5 rounded transition-opacity hover:opacity-80"
                      style={{ background: "var(--accent)", color: "#fff" }}
                    >
                      {acting === t.id ? "..." : "▶ 立即执行"}
                    </button>
                    {t.last_conversation_id && (
                      <button
                        onClick={() => { onSwitchSession(t.last_conversation_id); onClose(); }}
                        className="text-[10px] px-2 py-0.5 rounded transition-opacity hover:opacity-80"
                        style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)" }}
                      >
                        查看结果
                      </button>
                    )}
                    <button
                      onClick={() => startEdit(t)}
                      className="text-[10px] px-2 py-0.5 rounded transition-opacity hover:opacity-80"
                      style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)" }}
                    >
                      编辑
                    </button>
                    <button
                      onClick={() => handleDelete(t.id)} disabled={acting === t.id}
                      className="text-[10px] px-2 py-0.5 rounded transition-opacity hover:opacity-80"
                      style={{ background: "#2d1215", color: "#fca5a5" }}
                    >
                      删除
                    </button>
                  </div>
                </div>
              ))
            )}
          </>
        ) : (
          <div>
            <label className="block text-xs font-medium mb-1" style={{ color: "var(--text-primary)" }}>任务名称</label>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="w-full mb-3 px-3 py-2 rounded-lg text-sm outline-none" style={{ background: "var(--bg-primary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              placeholder="如：每日新闻汇总" />

            <label className="block text-xs font-medium mb-1" style={{ color: "var(--text-primary)" }}>提示词</label>
            <textarea value={form.prompt} onChange={(e) => setForm({ ...form, prompt: e.target.value })}
              className="w-full mb-3 px-3 py-2 rounded-lg text-sm outline-none resize-none" rows={3}
              style={{ background: "var(--bg-primary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              placeholder="定时发送给 AI 的问题" />

            <label className="block text-xs font-medium mb-1" style={{ color: "var(--text-primary)" }}>cron 表达式 (分 时 日 月 周)</label>
            <input value={form.cron_expression} onChange={(e) => setForm({ ...form, cron_expression: e.target.value })}
              className="w-full mb-1 px-3 py-2 rounded-lg text-sm font-mono outline-none" style={{ background: "var(--bg-primary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              placeholder="0 9 * * *" />
            {form.cron_expression && <div className="text-[10px] mb-3" style={{ color: "var(--text-secondary)" }}>→ {cronToHuman(form.cron_expression)}</div>}

            <label className="block text-xs font-medium mb-1" style={{ color: "var(--text-primary)" }}>模型 (可选)</label>
            <input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })}
              className="w-full mb-4 px-3 py-2 rounded-lg text-sm outline-none" style={{ background: "var(--bg-primary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              placeholder="留空使用默认模型" />

            <div className="flex items-center gap-2">
              <button
                onClick={handleSubmit} disabled={loading}
                className="flex-1 py-2 rounded-lg text-sm font-medium transition-opacity hover:opacity-80"
                style={{ background: "var(--accent)", color: "#fff" }}
              >
                {loading ? "..." : editingId ? "保存修改" : "创建任务"}
              </button>
              <button
                onClick={resetForm}
                className="flex-1 py-2 rounded-lg text-sm transition-opacity hover:opacity-80"
                style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)" }}
              >
                取消
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

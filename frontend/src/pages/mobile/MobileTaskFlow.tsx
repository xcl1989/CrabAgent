/**
 * MobileTaskFlow — /m 首页任务流（屏 1）。
 *
 * 三个区块，全部复用现有 API，零后端改动：
 *  1. 等你处理 — GET /task-requests?status=pending（approval / choice / input / human_step / review）
 *     决策走 POST /task-requests/{key}/approve | /reject（answer 用于 choice/input 回答）
 *  2. 运行中  — GET /agents/monitor（含浏览器协作外的所有活跃 Agent 会话）
 *  3. 待办任务 — GET /tasks?status=pending
 *
 * 10s 轮询 + visibilitychange 刷新；收到深链 request_key 时高亮对应卡片。
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import { getAgentMonitor, AgentMonitorInfo } from "../../api/monitor";
import { listTasks, Task } from "../../api/tasks";

export interface TaskRequestItem {
  request_key: string;
  session_id: string | null;
  request_type: "input" | "choice" | "approval" | "human_step" | "review" | string;
  operation: string | null;
  title: string;
  description: string | null;
  question: string | null;
  options: string[] | null;
  risk_level: "low" | "medium" | "high" | "critical" | null;
  display_payload: Record<string, unknown> | null;
  created_at: string | null;
  status: string;
}

interface Props {
  /** 深链带来的 request_key（#/m/approve/<key>），用于置顶高亮 */
  focusKey?: string;
  onOpenSession: (sessionId: string) => void;
}

const RISK_STYLES: Record<string, string> = {
  high: "bg-red-500/15 text-red-400",
  critical: "bg-red-500/25 text-red-300",
  medium: "bg-amber-500/15 text-amber-400",
  low: "bg-zinc-500/15 text-zinc-400",
};

const TYPE_STYLES: Record<string, { badge: string; label: string }> = {
  approval: { badge: "bg-amber-500/20 text-amber-400", label: "approval" },
  choice: { badge: "bg-purple-500/20 text-purple-300", label: "question" },
  input: { badge: "bg-purple-500/20 text-purple-300", label: "question" },
  human_step: { badge: "bg-blue-500/20 text-blue-300", label: "humanStep" },
  review: { badge: "bg-blue-500/20 text-blue-300", label: "review" },
};

function elapsedLabel(startedAt: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - startedAt));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h${Math.floor((s % 3600) / 60)}`;
}

function waitedLabel(iso: string | null): string {
  if (!iso) return "";
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h${Math.floor((s % 3600) / 60)}`;
}

export function MobileTaskFlow({ focusKey, onOpenSession }: Props) {
  const { t } = useTranslation();
  const [requests, setRequests] = useState<TaskRequestItem[]>([]);
  const [running, setRunning] = useState<AgentMonitorInfo[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    const [reqRes, runRes, taskRes] = await Promise.allSettled([
      api.get<{ requests: TaskRequestItem[] }>("/task-requests", { status: "pending" }),
      getAgentMonitor(),
      listTasks("pending"),
    ]);
    if (reqRes.status === "fulfilled") setRequests(reqRes.value.requests ?? []);
    if (runRes.status === "fulfilled") setRunning(runRes.value ?? []);
    if (taskRes.status === "fulfilled") setTasks(taskRes.value ?? []);
    setLoaded(true);
  }, []);

  useEffect(() => {
    void fetchAll();
    const timer = setInterval(() => void fetchAll(), 10000);
    const onVisible = () => document.visibilityState === "visible" && void fetchAll();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [fetchAll]);

  const decide = useCallback(
    async (key: string, decision: "approve" | "reject", answer?: string) => {
      setBusyKey(key);
      try {
        await api.post(`/task-requests/${encodeURIComponent(key)}/${decision}`, answer ? { answer } : {});
        setRequests((prev) => prev.filter((r) => r.request_key !== key));
      } catch {
        // 决策失败（409 资源变更 / 已过期）— 刷新拿最新状态
        void fetchAll();
      } finally {
        setBusyKey(null);
      }
    },
    [fetchAll],
  );

  return (
    <div className="flex flex-col gap-5 px-4 pt-3 pb-24">
      {/* ── 等你处理 ── */}
      <section>
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-2">
          {t("mobile.awaiting", { count: requests.length })}
        </h2>
        {loaded && requests.length === 0 && (
          <p className="text-[13px] text-zinc-600 px-1">{t("mobile.noPending")}</p>
        )}
        {requests.map((r) => {
          const meta = TYPE_STYLES[r.request_type] ?? TYPE_STYLES.review;
          const isFocused = focusKey === r.request_key;
          const isBusy = busyKey === r.request_key;
          return (
            <div
              key={r.request_key}
              className={`rounded-2xl border p-3.5 mb-2.5 ${
                r.request_type === "approval"
                  ? "border-amber-500/60 bg-gradient-to-b from-amber-950/40 to-zinc-900/60"
                  : "border-purple-500/50 bg-gradient-to-b from-purple-950/30 to-zinc-900/60"
              } ${isFocused ? "ring-2 ring-blue-400" : ""}`}
            >
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <div className="flex items-center gap-1.5">
                  <span className={`text-[10.5px] font-semibold px-2 py-0.5 rounded-full ${meta.badge}`}>
                    {t(`mobile.${meta.label}`)}
                  </span>
                  {(r.risk_level === "high" || r.risk_level === "critical") && (
                    <span className={`text-[10.5px] font-semibold px-2 py-0.5 rounded-full ${RISK_STYLES[r.risk_level]}`}>
                      {t("mobile.riskHigh")}
                    </span>
                  )}
                </div>
                {r.created_at && (
                  <span className="text-[11px] text-zinc-500 whitespace-nowrap">
                    {t("mobile.waited", { time: waitedLabel(r.created_at) })}
                  </span>
                )}
              </div>
              <h3 className="text-[14.5px] font-semibold leading-snug">{r.title}</h3>
              {r.description && (
                <p className="text-[12px] text-zinc-400 mt-1 leading-relaxed">{r.description}</p>
              )}
              {r.operation && r.request_type === "approval" && (
                <pre className="font-mono text-[11px] bg-black/40 border border-zinc-800 rounded-lg px-2.5 py-2 mt-2 text-sky-300 whitespace-pre-wrap break-all">
                  {r.operation}
                </pre>
              )}

              {/* choice：选项点选即回；input：自由回答 */}
              {(r.request_type === "choice" || r.request_type === "input") && (
                <div className="mt-2.5 flex flex-col gap-1.5">
                  {(r.options ?? []).map((opt) => (
                    <button
                      key={opt}
                      disabled={isBusy}
                      onClick={() => void decide(r.request_key, "approve", opt)}
                      className="text-left text-[13px] bg-zinc-800/70 border border-zinc-700 rounded-xl px-3 py-2.5 active:bg-zinc-700/70 flex justify-between items-center"
                    >
                      <span>{opt}</span>
                      <span className="text-zinc-500">›</span>
                    </button>
                  ))}
                  <FreeAnswer
                    value={answers[r.request_key] ?? ""}
                    disabled={isBusy}
                    onChange={(v) => setAnswers((p) => ({ ...p, [r.request_key]: v }))}
                    onSubmit={() => void decide(r.request_key, "approve", answers[r.request_key])}
                  />
                </div>
              )}

              {/* approval / human_step / review：批准 / 拒绝 */}
              {(r.request_type === "approval" || r.request_type === "human_step" || r.request_type === "review") && (
                <div className="flex gap-2 mt-3">
                  <button
                    disabled={isBusy}
                    onClick={() => void decide(r.request_key, "reject")}
                    className="flex-1 py-2.5 rounded-xl text-[14px] font-semibold bg-red-500/10 text-red-400 border border-red-500/35 active:bg-red-500/20"
                  >
                    {t("mobile.reject")}
                  </button>
                  <button
                    disabled={isBusy}
                    onClick={() => void decide(r.request_key, "approve")}
                    className="flex-1 py-2.5 rounded-xl text-[14px] font-semibold bg-green-500/15 text-green-400 border border-green-500/45 active:bg-green-500/30"
                  >
                    {r.request_type === "approval" ? t("mobile.approve") : t("mobile.doneStep")}
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </section>

      {/* ── 运行中 ── */}
      <section>
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-2">
          {t("mobile.running", { count: running.length })}
        </h2>
        {running.map((a) => (
          <button
            key={a.session_id}
            onClick={() => onOpenSession(a.session_id)}
            className="w-full text-left rounded-2xl border border-zinc-800 bg-zinc-900/70 p-3.5 mb-2.5 active:bg-zinc-800/70"
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10.5px] font-semibold px-2 py-0.5 rounded-full bg-green-500/15 text-green-400">
                {t("mobile.statusRunning")}
              </span>
              <span className="text-[11px] text-zinc-500">{elapsedLabel(a.started_at)}</span>
            </div>
            <h3 className="text-[14px] font-semibold leading-snug">{a.title || a.session_id}</h3>
            <p className="text-[12px] text-zinc-500 mt-1">{a.model}</p>
          </button>
        ))}
        {loaded && running.length === 0 && (
          <p className="text-[13px] text-zinc-600 px-1">{t("mobile.noRunning")}</p>
        )}
      </section>

      {/* ── 待办任务 ── */}
      {tasks.length > 0 && (
        <section>
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-2">
            {t("mobile.tasks", { count: tasks.length })}
          </h2>
          {tasks.map((task) => (
            <div key={task.id} className="rounded-2xl border border-zinc-800 bg-zinc-900/70 p-3.5 mb-2.5">
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10.5px] font-semibold px-2 py-0.5 rounded-full bg-zinc-500/15 text-zinc-400">
                  {task.status}
                </span>
                {task.deadline && <span className="text-[11px] text-zinc-500">📅 {task.deadline.slice(0, 10)}</span>}
              </div>
              <h3 className="text-[14px] font-semibold leading-snug">{task.title}</h3>
              {task.result_summary && (
                <p className="text-[12px] text-zinc-500 mt-1 line-clamp-2">{task.result_summary}</p>
              )}
            </div>
          ))}
        </section>
      )}
    </div>
  );
}

function FreeAnswer({
  value,
  disabled,
  onChange,
  onSubmit,
}: {
  value: string;
  disabled: boolean;
  onChange: (v: string) => void;
  onSubmit: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex gap-2 items-center mt-1">
      <input
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && value.trim() && onSubmit()}
        placeholder={t("mobile.otherReply")}
        className="flex-1 bg-zinc-800/70 border border-zinc-700 rounded-xl px-3 py-2.5 text-[13px] outline-none focus:border-purple-500/60"
      />
      {value.trim() && (
        <button
          disabled={disabled}
          onClick={onSubmit}
          className="w-9 h-9 rounded-full bg-green-500 text-black font-bold active:scale-95"
        >
          ➤
        </button>
      )}
    </div>
  );
}

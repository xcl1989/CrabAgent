import { Goal, Pause, Play, Target, CheckCircle2, CircleAlert, Pencil } from "lucide-react";
import { Goal as GoalData } from "../types/Goal";

interface Props {
  goal: GoalData;
  busy?: boolean;
  onPause: () => void;
  onResume: () => void;
  onEdit: () => void;
  onHistory: () => void;
}

const statusStyle = {
  active: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300",
  paused: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  budget_limited: "bg-orange-500/15 text-orange-700 dark:text-orange-300",
  complete: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300",
  unmet: "bg-red-500/15 text-red-700 dark:text-red-300",
  cleared: "bg-[var(--bg-tertiary)] text-[var(--text-tertiary)]",
};

const statusLabel = {
  active: "进行中",
  paused: "已暂停",
  budget_limited: "预算已到",
  complete: "已完成",
  unmet: "遇到阻塞",
  cleared: "已归档",
};

export function GoalCard({ goal, busy, onPause, onResume, onEdit, onHistory }: Props) {
  const isDone = goal.status === "complete" || goal.status === "unmet" || goal.status === "cleared";
  const detail = goal.status === "complete" ? goal.completion_evidence : goal.status === "unmet" ? goal.blocker : goal.latest_checkpoint;

  return (
    <section className="mx-3 mt-3 rounded-2xl border border-[var(--border)] bg-[var(--bg-secondary)] shadow-[var(--shadow-sm)] overflow-hidden">
      <div className="flex items-start gap-3 p-3.5">
        <div className="mt-0.5 h-8 w-8 shrink-0 rounded-xl bg-[var(--brand)]/12 text-[var(--brand)] flex items-center justify-center">
          <Target size={17} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${statusStyle[goal.status]}`}>
              {goal.status === "complete" ? <CheckCircle2 size={11} /> : goal.status === "unmet" ? <CircleAlert size={11} /> : <Goal size={11} />}
              {statusLabel[goal.status]}
            </span>
            {!isDone && <span className="text-[11px] text-[var(--text-tertiary)]">目标模式</span>}
          </div>
          <p className="mt-1 text-sm font-medium text-[var(--text-primary)] line-clamp-2">{goal.objective}</p>
          {detail && <p className="mt-1 text-xs text-[var(--text-secondary)] line-clamp-2">{detail}</p>}
          {goal.next_step && !isDone && <p className="mt-1 text-[11px] text-[var(--text-tertiary)]">下一步：{goal.next_step}</p>}
        </div>
        <div className="flex shrink-0 gap-1">
          {!isDone && goal.status === "active" && <button onClick={onPause} disabled={busy} title="暂停目标" className="p-2 rounded-lg hover:bg-[var(--bg-tertiary)] text-[var(--text-secondary)] disabled:opacity-50"><Pause size={15} /></button>}
          {!isDone && goal.status !== "active" && <button onClick={onResume} disabled={busy} title="继续目标" className="p-2 rounded-lg hover:bg-[var(--bg-tertiary)] text-[var(--brand)] disabled:opacity-50"><Play size={15} /></button>}
          <button onClick={onHistory} title="查看目标进展" className="px-2 text-[11px] rounded-lg hover:bg-[var(--bg-tertiary)] text-[var(--text-secondary)]">进展</button>
          <button onClick={onEdit} disabled={busy} title="编辑目标" className="p-2 rounded-lg hover:bg-[var(--bg-tertiary)] text-[var(--text-secondary)] disabled:opacity-50"><Pencil size={15} /></button>
        </div>
      </div>
      {(goal.success_criteria.length > 0 || goal.token_budget) && <div className="border-t border-[var(--border-subtle)] px-3.5 py-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[var(--text-tertiary)]">
        {goal.success_criteria.length > 0 && <span>{goal.success_criteria.length} 项验收条件</span>}
        {goal.token_budget && <span>{goal.tokens_used.toLocaleString()} / {goal.token_budget.toLocaleString()} tokens</span>}
      </div>}
    </section>
  );
}

import { TaskInfo, TaskStatus } from "./TaskBoard.types";

const AGENT_ICONS: Record<string, string> = {
  researcher: "🔍", analyst: "📊", coder: "💻", writer: "📝",
};

interface Props {
  task: TaskInfo;
  onClick: () => void;
}

export function TaskCard({ task, onClick }: Props) {
  const statusConfig: Record<TaskStatus, { border: string; bg: string; badge: string; label: string }> = {
    running: { border: "var(--accent-2)", bg: "var(--accent-2-bg)", badge: "var(--accent-2)", label: "Running" },
    done: { border: "var(--success)", bg: "var(--success-bg)", badge: "var(--success)", label: "Done" },
    error: { border: "var(--danger)", bg: "var(--danger-bg)", badge: "var(--danger)", label: "Error" },
  };

  const cfg = statusConfig[task.status];
  const icon = task.icon || AGENT_ICONS[task.agentName] || "🤖";

  return (
    <button
      onClick={onClick}
      className="w-full text-left rounded-lg p-3 transition-all hover:scale-[1.01] active:scale-[0.99]"
      style={{
        background: cfg.bg,
        border: `1px solid ${cfg.border}30`,
        boxShadow: task.status === "running" ? `0 0 12px ${cfg.border}20` : "none",
      }}
    >
      <div className="flex items-center gap-2.5 mb-1.5">
        <span className="text-base">{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold truncate" style={{ color: "var(--text-primary)" }}>
              {task.displayName}
            </span>
            <span
              className="text-[9px] px-1.5 py-0.5 rounded-full font-medium shrink-0"
              style={{ background: `${cfg.badge}20`, color: cfg.badge }}
            >
              {task.status === "running" && (
                <span className="inline-block w-1.5 h-1.5 rounded-full mr-1 animate-pulse" style={{ background: cfg.badge }} />
              )}
              {cfg.label}
            </span>
          </div>
        </div>
      </div>

      <p className="text-[10px] leading-relaxed mb-1.5 line-clamp-2" style={{ color: "var(--text-secondary)" }}>
        {task.task}
      </p>

      <div className="flex items-center gap-3 text-[9px]" style={{ color: "var(--text-secondary)" }}>
        {task.status === "running" && (
          <>
            {task.toolCalls > 0 && <span>⚡ {task.toolCalls} tools</span>}
            <span>⏱ {Math.round((Date.now() - task.startedAt) / 1000)}s</span>
          </>
        )}
        {task.status === "done" && (
          <>
            {task.elapsed != null && <span>⏱ {task.elapsed}s</span>}
            {task.tokens != null && <span>🎫 {task.tokens}</span>}
            {task.iterations != null && <span>🔄 {task.iterations} steps</span>}
          </>
        )}
        {task.status === "error" && task.error && (
          <span className="truncate" style={{ color: "var(--danger)" }}>{task.error}</span>
        )}
      </div>
    </button>
  );
}

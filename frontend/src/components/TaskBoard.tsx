import { useState } from "react";
import { ClipboardList, ChevronRight } from "lucide-react";
import { TaskInfo } from "./TaskBoard.types";
import { TaskCard } from "./TaskCard";

interface Props {
  tasks: TaskInfo[];
  onTaskClick: (task: TaskInfo) => void;
}

export function TaskBoard({ tasks, onTaskClick }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const runningCount = tasks.filter((t) => t.status === "running").length;

  if (tasks.length === 0) return null;

  return (
    <div
      className="shrink-0 flex flex-col transition-all duration-200 overflow-hidden border-l border-[var(--border)] bg-[var(--bg-primary)]"
      style={{ width: collapsed ? 44 : 280 }}
    >
      <div
        className="flex items-center shrink-0 cursor-pointer select-none border-b border-[var(--border)]"
        style={{ padding: collapsed ? "8px 0" : "8px 12px" }}
        onClick={() => setCollapsed(!collapsed)}
      >
        {!collapsed ? (
          <>
            <span className="text-xs font-semibold text-[var(--text-primary)] flex items-center gap-1.5">
              <ClipboardList size={12} />
              Tasks
            </span>
            {runningCount > 0 && (
              <span className="ml-2 text-[9px] px-1.5 py-0.5 rounded-full font-medium animate-pulse bg-[var(--accent-2-bg)] text-[var(--accent-2)]">
                {runningCount} running
              </span>
            )}
            <ChevronRight
              size={12}
              className="ml-auto text-[var(--text-secondary)]"
            />
          </>
        ) : (
          <div className="flex flex-col items-center w-full gap-1">
            <ClipboardList
              size={14}
              className="text-[var(--text-primary)]"
            />
            {runningCount > 0 && (
              <span className="w-4 h-4 rounded-full text-[8px] font-bold flex items-center justify-center bg-[var(--accent-2)] text-[var(--text-on-accent)]">
                {runningCount}
              </span>
            )}
          </div>
        )}
      </div>

      {!collapsed && (
        <div className="flex-1 overflow-y-auto p-2 space-y-2">
          {tasks.map((t) => (
            <TaskCard
              key={t.subId}
              task={t}
              onClick={() => onTaskClick(t)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

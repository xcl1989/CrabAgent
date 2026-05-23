import { useState } from "react";
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
      className="shrink-0 flex flex-col transition-all duration-200 overflow-hidden"
      style={{
        width: collapsed ? 44 : 280,
        borderLeft: "1px solid var(--border)",
        background: "var(--bg-primary)",
      }}
    >
      <div
        className="flex items-center shrink-0 cursor-pointer select-none"
        style={{ borderBottom: "1px solid var(--border)", padding: collapsed ? "8px 0" : "8px 12px" }}
        onClick={() => setCollapsed(!collapsed)}
      >
        {!collapsed ? (
          <>
            <span className="text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
              Tasks
            </span>
            {runningCount > 0 && (
              <span
                className="ml-2 text-[9px] px-1.5 py-0.5 rounded-full font-medium animate-pulse"
                style={{ background: "var(--accent-2-bg)", color: "var(--accent-2)" }}
              >
                {runningCount} running
              </span>
            )}
            <span className="ml-auto text-[10px]" style={{ color: "var(--text-secondary)" }}>▸</span>
          </>
        ) : (
          <div className="flex flex-col items-center w-full gap-1">
            <span className="text-xs" style={{ color: "var(--text-primary)" }}>📋</span>
            {runningCount > 0 && (
              <span
                className="w-4 h-4 rounded-full text-[8px] font-bold flex items-center justify-center"
                style={{ background: "var(--accent-2)", color: "var(--text-on-accent)" }}
              >
                {runningCount}
              </span>
            )}
          </div>
        )}
      </div>

      {!collapsed && (
        <div className="flex-1 overflow-y-auto p-2 space-y-2">
          {tasks.map((t) => (
            <TaskCard key={t.subId} task={t} onClick={() => onTaskClick(t)} />
          ))}
        </div>
      )}
    </div>
  );
}

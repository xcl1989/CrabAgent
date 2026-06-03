import { useState } from "react";
import { ClipboardList, ChevronRight, X } from "lucide-react";
import { TaskInfo } from "./TaskBoard.types";
import { TaskCard } from "./TaskCard";

interface Props {
  tasks: TaskInfo[];
  onTaskClick: (task: TaskInfo) => void;
}

function DesktopTaskBoard({ tasks, onTaskClick }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const runningCount = tasks.filter((t) => t.status === "running").length;

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

function MobileTaskDrawer({ tasks, onTaskClick }: Props) {
  const [open, setOpen] = useState(false);
  const runningCount = tasks.filter((t) => t.status === "running").length;

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-36 sm:bottom-32 left-3 z-40 flex items-center gap-1.5 h-9 px-3 rounded-full text-[11px] font-medium shadow-[var(--shadow-md)] bg-[var(--bg-secondary)] border border-[var(--border)] text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
      >
        <ClipboardList size={13} className="text-[var(--accent-2)]" />
        Tasks
        {runningCount > 0 && (
          <span className="w-4 h-4 rounded-full text-[8px] font-bold flex items-center justify-center bg-[var(--accent-2)] text-[var(--text-on-accent)] animate-pulse">
            {runningCount}
          </span>
        )}
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-40 bg-[var(--bg-overlay)] backdrop-blur-sm animate-fade-in"
            onClick={() => setOpen(false)}
          />
          <div className="fixed bottom-0 left-0 right-0 z-50 bg-[var(--bg-secondary)] border-t border-[var(--border)] rounded-t-2xl shadow-[var(--shadow-lg)] animate-slide-up max-h-[60vh] flex flex-col">
            <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-subtle)]">
              <span className="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-2">
                <ClipboardList size={14} className="text-[var(--accent-2)]" />
                Tasks
                {runningCount > 0 && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium animate-pulse bg-[var(--accent-2-bg)] text-[var(--accent-2)]">
                    {runningCount} running
                  </span>
                )}
              </span>
              <button
                onClick={() => setOpen(false)}
                className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
              >
                <X size={16} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
              {tasks.map((t) => (
                <TaskCard
                  key={t.subId}
                  task={t}
                  onClick={() => {
                    onTaskClick(t);
                    setOpen(false);
                  }}
                />
              ))}
            </div>
          </div>
        </>
      )}
    </>
  );
}

export function TaskBoard(props: Props) {
  if (props.tasks.length === 0) return null;

  return (
    <>
      <div className="hidden md:block">
        <DesktopTaskBoard {...props} />
      </div>
      <div className="md:hidden">
        <MobileTaskDrawer {...props} />
      </div>
    </>
  );
}

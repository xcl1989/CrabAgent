import { useState } from "react";
import { TaskInfo } from "./TaskBoard.types";

interface Props {
  tasks: TaskInfo[];
  onClose: () => void;
  onExport: () => void;
}

export function ResultCompare({ tasks, onClose, onExport }: Props) {
  const [activeTab, setActiveTab] = useState<string>(tasks[0]?.subId || "");

  const completed = tasks.filter((t) => t.status === "done" || t.status === "error");
  if (completed.length === 0) return null;

  const active = completed.find((t) => t.subId === activeTab) || completed[0];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.6)" }}>
      <div
        className="flex flex-col rounded-xl overflow-hidden"
        style={{
          background: "var(--bg-secondary)",
          border: "1px solid var(--border)",
          width: "min(900px, 92vw)",
          maxHeight: "85vh",
          boxShadow: "0 25px 60px rgba(0,0,0,0.5)",
        }}
      >
        <div className="flex items-center justify-between px-5 py-3 shrink-0" style={{ borderBottom: "1px solid var(--border)" }}>
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              Results ({completed.length} agents)
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onExport}
              className="text-[10px] px-3 py-1 rounded-md transition-opacity hover:opacity-80"
              style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)" }}
            >
              Export Report
            </button>
            <button onClick={onClose} className="text-sm opacity-60 hover:opacity-100" style={{ color: "var(--text-secondary)" }}>
              ✕
            </button>
          </div>
        </div>

        <div className="flex flex-1 min-h-0">
          <div className="w-48 shrink-0 overflow-y-auto p-3 space-y-1.5" style={{ borderRight: "1px solid var(--border)", background: "var(--bg-primary)" }}>
            {completed.map((t) => (
              <button
                key={t.subId}
                onClick={() => setActiveTab(t.subId)}
                className="w-full text-left px-2.5 py-2 rounded-lg text-xs transition-all"
                style={{
                  background: active?.subId === t.subId ? "var(--bg-tertiary)" : "transparent",
                  border: `1px solid ${active?.subId === t.subId ? "var(--border)" : "transparent"}`,
                  color: t.status === "error" ? "var(--danger)" : "var(--text-primary)",
                }}
              >
                <div className="flex items-center gap-1.5">
                  <span>{t.icon || "🤖"}</span>
                  <span className="font-medium truncate">{t.displayName}</span>
                </div>
                <div className="text-[9px] mt-0.5" style={{ color: "var(--text-secondary)" }}>
                  {t.elapsed != null && `${t.elapsed}s`}
                  {t.elapsed != null && t.tokens != null && " · "}
                  {t.tokens != null && `${t.tokens} tok`}
                </div>
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto p-5">
            {active && (
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-lg">{active.icon || "🤖"}</span>
                  <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                    {active.displayName}
                  </span>
                  <span className="text-[9px] px-1.5 py-0.5 rounded-full"
                    style={{
                      background: active.status === "done" ? "var(--success-bg)" : "var(--danger-bg)",
                      color: active.status === "done" ? "var(--success)" : "var(--danger)",
                    }}>
                    {active.status === "done" ? "Completed" : "Failed"}
                  </span>
                </div>
                {active.task && (
                  <p className="text-[10px] mb-3 italic" style={{ color: "var(--text-secondary)" }}>
                    Task: {active.task}
                  </p>
                )}
                <div className="text-xs leading-relaxed whitespace-pre-wrap" style={{ color: "var(--text-primary)" }}>
                  {active.content || "(no output)"}
                </div>
                {active.error && (
                  <div className="mt-3 p-2.5 rounded-lg text-xs" style={{ background: "var(--danger-bg)", color: "var(--danger)", border: "1px solid var(--danger-border)" }}>
                    {active.error}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

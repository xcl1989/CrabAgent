import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Download } from "lucide-react";
import { TaskInfo } from "./TaskBoard.types";
import { Modal, Button } from "./ui";
import { useTranslation } from "react-i18next";
import { cn } from "../lib/cn";

interface Props {
  tasks: TaskInfo[];
  onClose: () => void;
  onExport: () => void;
}

export function ResultCompare({ tasks, onClose, onExport }: Props) {
  const { t: tr } = useTranslation();
  const completed = tasks.filter(
    (t) => t.status === "done" || t.status === "error",
  );
  const [activeTab, setActiveTab] = useState<string>(
    completed[0]?.subId || "",
  );

  if (completed.length === 0) return null;

  const active = completed.find((t) => t.subId === activeTab) || completed[0];

  return (
    <Modal
      open={true}
      onOpenChange={(o) => !o && onClose()}
      title={`Results · ${completed.length} agent${completed.length !== 1 ? "s" : ""}`}
      size="xl"
      hideClose
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button variant="primary" onClick={onExport}>
            <Download size={14} /> Export Report
          </Button>
        </>
      }
    >
      <div className="-mx-5 -my-4 flex h-[60vh]">
        <aside className="w-48 shrink-0 overflow-y-auto border-r border-[var(--border)] bg-[var(--bg-primary)] p-2 space-y-1">
          {completed.map((t) => {
            const isActive = active?.subId === t.subId;
            return (
              <button
                key={t.subId}
                onClick={() => setActiveTab(t.subId)}
                className={cn(
                  "w-full text-left px-2.5 py-2 rounded-lg text-xs transition-colors",
                  isActive
                    ? "bg-[var(--bg-tertiary)] text-[var(--text-primary)] border border-[var(--border)]"
                    : "text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)] border border-transparent",
                  t.status === "error" && "text-[var(--danger)]",
                )}
              >
                <div className="flex items-center gap-1.5">
                  <span>{t.icon || "🤖"}</span>
                  <span className="font-medium truncate">{t.displayName}</span>
                </div>
                <div className="text-[10px] mt-0.5 font-mono text-[var(--text-tertiary)]">
                  {t.elapsed != null && `${t.elapsed}s`}
                  {t.elapsed != null && t.tokens != null && " · "}
                  {t.tokens != null && `${t.tokens} tok`}
                </div>
              </button>
            );
          })}
        </aside>

        <div className="flex-1 overflow-y-auto p-5">
          {active && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <span className="text-lg">{active.icon || "🤖"}</span>
                <span className="text-sm font-semibold text-[var(--text-primary)]">
                  {active.displayName}
                </span>
                <span
                  className={cn(
                    "text-[10px] px-2 py-0.5 rounded-full font-medium",
                    active.status === "done"
                      ? "bg-[var(--success-bg)] text-[var(--success)] border border-[var(--success-border)]"
                      : "bg-[var(--danger-bg)] text-[var(--danger)] border border-[var(--danger-border)]",
                  )}
                >
                  {active.status === "done" ? tr("resultCompare.completed") : tr("resultCompare.failed")}
                </span>
              </div>
              {active.task && (
                <p className="text-[11px] mb-3 italic text-[var(--text-tertiary)]">
                  Task: {active.task}
                  {tr("resultCompare.task")}: {active.task}
                </p>
              )}
              <div className="markdown-body text-sm">
                {active.content ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {active.content}
                  </ReactMarkdown>
                ) : (
                  <span className="text-[var(--text-tertiary)] italic">
                    (no output)
                  </span>
                )}
              </div>
              {active.error && (
                <div className="mt-3 p-2.5 rounded-lg text-xs bg-[var(--danger-bg)] text-[var(--danger)] border border-[var(--danger-border)]">
                  {active.error}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}

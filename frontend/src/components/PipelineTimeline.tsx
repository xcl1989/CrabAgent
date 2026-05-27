import { useState } from "react";

interface PipelineStep {
  id: string;
  agentName: string;
  task: string;
  status: "pending" | "running" | "done" | "error";
  elapsed?: number;
  resultSummary?: string;
}

interface PipelineTimelineProps {
  steps: PipelineStep[];
  totalSteps: number;
  completedCount: number;
  failedCount: number;
  finished?: boolean;
  historical?: boolean;
}

export default function PipelineTimeline({ steps, totalSteps, completedCount, failedCount, finished, historical }: PipelineTimelineProps) {
  const [expanded, setExpanded] = useState(true);
  const [expandedStep, setExpandedStep] = useState<string | null>(null);

  const statusLabel = finished
    ? failedCount > 0
      ? `Pipeline: ${completedCount}/${totalSteps} (${failedCount} failed)`
      : `Pipeline: ${completedCount}/${totalSteps} complete`
    : `Pipeline: ${completedCount}/${totalSteps}`;

  if (!expanded) {
    return (
      <div
        className="rounded-lg overflow-hidden"
        style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", opacity: historical ? 0.8 : 1 }}
      >
        <div
          className="flex items-center justify-between px-4 py-2.5 cursor-pointer"
          onClick={() => setExpanded(true)}
        >
          <div className="flex items-center gap-2 text-xs font-medium" style={{ color: "var(--text-primary)", fontFamily: "'SF Mono', monospace" }}>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2 2h3v3H2V2Zm5 0h3v3H7V2ZM2 7h3v3H2V7Zm5 0h3v3H7V7Z" fill="#60a5fa"/></svg>
            <span>{statusLabel}</span>
            {historical && <span style={{ color: "var(--text-tertiary)", fontSize: 10 }}>(history)</span>}
          </div>
          <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>Expand</span>
        </div>
      </div>
    );
  }

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{
        background: "var(--bg-secondary)",
        border: `1px solid ${failedCount > 0 ? "#f8717140" : finished ? "var(--border)" : "#34d39940"}`,
        opacity: historical ? 0.8 : 1,
      }}
    >
      <div
        className="flex items-center justify-between px-4 py-2.5 cursor-pointer"
        style={{ borderBottom: "1px solid var(--border)" }}
        onClick={() => setExpanded(false)}
      >
        <div className="flex items-center gap-2 text-xs font-medium" style={{ color: "var(--text-primary)", fontFamily: "'SF Mono', monospace" }}>
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2 2h3v3H2V2Zm5 0h3v3H7V2ZM2 7h3v3H2V7Zm5 0h3v3H7V7Z" fill="#60a5fa"/></svg>
          <span>{statusLabel}</span>
          {historical && <span style={{ color: "var(--text-tertiary)", fontSize: 10 }}>(history)</span>}
        </div>
        <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>Collapse</span>
      </div>

      <div className="px-4 py-3">
        <div className="flex items-start gap-2">
          {steps.map((step, i) => {
            const isLast = i === steps.length - 1;
            const statusConfig = STATUS_CONFIG[step.status];
            return (
              <div key={step.id} className="flex items-start" style={{ flex: 1 }}>
                <div className="flex flex-col items-center" style={{ flex: 1 }}>
                  <div
                    className="rounded px-2 py-1.5 cursor-pointer transition-colors w-full"
                    style={{
                      background: statusConfig.bg,
                      border: `1px solid ${statusConfig.border}`,
                    }}
                    onClick={() => setExpandedStep(expandedStep === step.id ? null : step.id)}
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs" style={{ color: statusConfig.text }}>{statusConfig.icon}</span>
                      <span className="text-xs font-medium truncate" style={{ color: "var(--text-primary)", fontFamily: "'SF Mono', monospace" }}>
                        {step.agentName}
                      </span>
                    </div>
                    <div className="text-xs mt-0.5 truncate" style={{ color: "var(--text-tertiary)", maxWidth: 120 }}>
                      {step.task.slice(0, 40)}
                    </div>
                    {step.status !== "pending" && (
                      <div className="text-xs mt-1" style={{ color: statusConfig.text }}>
                        {step.status === "running"
                          ? "running..."
                          : step.elapsed
                            ? `${step.elapsed.toFixed(1)}s`
                            : statusConfig.label}
                      </div>
                    )}
                  </div>

                  {expandedStep === step.id && step.resultSummary && (
                    <div
                      className="w-full mt-1 p-2 rounded text-xs"
                      style={{ background: "var(--bg-tertiary)", color: "var(--text-secondary)", maxHeight: 80, overflow: "auto" }}
                    >
                      {step.resultSummary.slice(0, 200)}
                    </div>
                  )}

                  {!isLast && (
                    <div
                      className="w-0.5 flex-1 min-h-6 mt-1 mb-1"
                      style={{ background: statusConfig.border }}
                    />
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <div className="flex mt-2 gap-3 text-xs" style={{ fontFamily: "'SF Mono', monospace" }}>
          {Object.entries(STATUS_CONFIG).map(([key, config]) => (
            <div key={key} className="flex items-center gap-1">
              <div className="w-2 h-2 rounded" style={{ background: config.border }} />
              <span style={{ color: "var(--text-tertiary)" }}>{config.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const STATUS_CONFIG: Record<string, { bg: string; border: string; text: string; icon: string; label: string }> = {
  pending: {
    bg: "var(--bg-tertiary)",
    border: "var(--border)",
    text: "var(--text-tertiary)",
    icon: "○",
    label: "pending",
  },
  running: {
    bg: "#1d4ed808",
    border: "#3b82f6",
    text: "#60a5fa",
    icon: "●",
    label: "running",
  },
  done: {
    bg: "#34d39908",
    border: "#34d399",
    text: "#34d399",
    icon: "✓",
    label: "done",
  },
  error: {
    bg: "#f8717108",
    border: "#f87171",
    text: "#f87171",
    icon: "✗",
    label: "error",
  },
};

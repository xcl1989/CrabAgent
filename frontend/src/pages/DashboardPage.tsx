import { useState, useEffect, useCallback, useRef } from "react";
import {
  Activity,
  Check,
  X as XIcon,
  Circle,
  PlayCircle,
  ChevronDown,
  ChevronRight,
  History as HistoryIcon,
} from "lucide-react";
import { connectGlobalSSE, GlobalSSEEvent } from "../api/monitor";
import {
  listAgentProfiles,
  AgentProfile,
  getPipelineHistory,
  PipelineHistoryItem,
} from "../api/agents";
import AgentGrowthChart from "../components/AgentGrowthChart";
import {
  useThemeColors,
  agentColor,
  type ThemeColors,
} from "../lib/theme-colors";
import { Modal } from "../components/ui";
import { cn } from "../lib/cn";

interface PipelineStep {
  id: string;
  agentName: string;
  task: string;
  status: "pending" | "running" | "done" | "error";
  elapsed?: number;
  resultSummary?: string;
}

interface PipelineState {
  pipelineId: string;
  sessionId: string;
  totalSteps: number;
  steps: PipelineStep[];
  completedCount: number;
  failedCount: number;
  finished: boolean;
  historical?: boolean;
  createdAt: number;
}

function agentBgVar(name: string): string {
  switch (name) {
    case "researcher":
      return "var(--agent-researcher-bg)";
    case "analyst":
      return "var(--agent-analyst-bg)";
    case "coder":
      return "var(--agent-coder-bg)";
    case "writer":
      return "var(--agent-writer-bg)";
    default:
      return "var(--bg-tertiary)";
  }
}

function agentBorderVar(name: string): string {
  switch (name) {
    case "researcher":
      return "var(--agent-researcher)";
    case "analyst":
      return "var(--agent-analyst)";
    case "coder":
      return "var(--agent-coder)";
    case "writer":
      return "var(--agent-writer)";
    default:
      return "var(--border)";
  }
}

export default function DashboardPage() {
  const [profiles, setProfiles] = useState<AgentProfile[]>([]);
  const [runningCounts, setRunningCounts] = useState<Record<string, number>>({});
  const [pipelines, setPipelines] = useState<PipelineState[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [historyExpanded, setHistoryExpanded] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const colors = useThemeColors();

  useEffect(() => {
    listAgentProfiles().then(setProfiles).catch(() => {});
    getPipelineHistory(10)
      .then((items) => {
        if (!items.length) return;
        const hist: PipelineState[] = items.map((p) => {
          const isFinished =
            p.status === "completed" ||
            p.status === "interrupted" ||
            p.status === "failed";
          return {
            pipelineId: String(p.id),
            sessionId: p.session_id || "",
            totalSteps:
              p.steps?.length || (p.metadata?.total_steps as number) || 0,
            steps: (p.steps || []).map((s) => ({
              id: String(s.id),
              agentName: s.agent_name,
              task: s.task_summary?.slice(0, 200) || "",
              status: (s.status === "completed"
                ? "done"
                : s.status === "failed" || s.status === "interrupted"
                  ? "error"
                  : s.status === "running"
                    ? "running"
                    : "pending") as PipelineStep["status"],
              elapsed: s.elapsed || undefined,
              resultSummary: s.result_summary?.slice(0, 300) || undefined,
            })),
            completedCount: (p.steps || []).filter(
              (s) => s.status === "completed",
            ).length,
            failedCount: (p.steps || []).filter(
              (s) => s.status === "failed" || s.status === "interrupted",
            ).length,
            finished: isFinished,
            historical: isFinished,
            createdAt: p.started_at ? p.started_at * 1000 : Date.now(),
          };
        });
        const counts: Record<string, number> = {};
        for (const p of hist) {
          if (!p.finished) {
            for (const s of p.steps) {
              if (s.status === "running" || s.status === "pending") {
                counts[s.agentName] = (counts[s.agentName] || 0) + 1;
              }
            }
          }
        }
        if (Object.keys(counts).length > 0) setRunningCounts(counts);

        setPipelines((prev) => {
          const liveIds = new Set(prev.map((p) => p.pipelineId));
          return [...prev, ...hist.filter((h) => !liveIds.has(h.pipelineId))];
        });
      })
      .catch(() => {});
  }, []);

  const handlePipelineStart = useCallback(
    (data: Record<string, unknown>, sid: string) => {
      const stepIds = (data.step_ids as string[]) || [];
      const stepAgents = (data.step_agents as Record<string, string>) || {};
      const stepTasks = (data.step_tasks as Record<string, string>) || {};
      const pid = data.pipeline_run_id
        ? String(data.pipeline_run_id)
        : Date.now().toString();

      setPipelines((prev) => {
        const filtered = prev.filter(
          (p) => p.finished || p.sessionId !== sid || p.pipelineId === pid,
        );
        if (filtered.some((p) => p.pipelineId === pid)) return filtered;
        return [
          {
            pipelineId: pid,
            sessionId: sid,
            totalSteps: (data.total_steps as number) || stepIds.length,
            steps: stepIds.map((id) => ({
              id,
              agentName: stepAgents[id] || "unknown",
              task: stepTasks[id] || "",
              status: "pending" as const,
            })),
            completedCount: 0,
            failedCount: 0,
            finished: false,
            createdAt: Date.now(),
          },
          ...filtered,
        ];
      });

      const counts: Record<string, number> = {};
      for (const id of stepIds) {
        const n = stepAgents[id] || "unknown";
        counts[n] = (counts[n] || 0) + 1;
      }
      setRunningCounts((prev) => {
        const next = { ...prev };
        for (const [n, c] of Object.entries(counts))
          next[n] = (next[n] || 0) + c;
        return next;
      });
    },
    [],
  );

  const handlePipelineStepEnd = useCallback(
    (data: Record<string, unknown>) => {
      const stepId = data.step_id as string;
      if (!stepId) return;
      setPipelines((prev) =>
        prev.map((p) => {
          if (p.finished || p.historical) return p;
          const step = p.steps.find((s) => s.id === stepId);
          if (step)
            setRunningCounts((prev) => ({
              ...prev,
              [step.agentName]: Math.max(
                0,
                (prev[step.agentName] || 0) - 1,
              ),
            }));
          return {
            ...p,
            steps: p.steps.map((s) =>
              s.id === stepId
                ? {
                    ...s,
                    status: "done" as const,
                    elapsed: data.elapsed as number,
                    resultSummary: (data.result as string)?.slice(0, 300),
                  }
                : s,
            ),
            completedCount: p.completedCount + 1,
          };
        }),
      );
    },
    [],
  );

  const handlePipelineEnd = useCallback(() => {
    setPipelines((prev) =>
      prev.map((p) =>
        p.finished || p.historical ? p : { ...p, finished: true },
      ),
    );
    setRunningCounts({});
  }, []);

  useEffect(() => {
    let pending: GlobalSSEEvent[] = [];
    let timer: ReturnType<typeof setTimeout> | null = null;
    const flush = () => {
      if (!pending.length) return;
      const batch = pending;
      pending = [];
      for (const ev of batch) {
        const sid = (ev.data.session_id as string | undefined) || "";
        if (ev.type === "pipeline_start") {
          handlePipelineStart(ev.data, sid);
          continue;
        }
        if (ev.type === "pipeline_step_start") {
          setPipelines((prev) =>
            prev.map((p) =>
              p.finished || p.historical
                ? p
                : {
                    ...p,
                    steps: p.steps.map((s) =>
                      s.id === ev.data.step_id
                        ? { ...s, status: "running" as const }
                        : s,
                    ),
                  },
            ),
          );
          continue;
        }
        if (ev.type === "pipeline_step_end") {
          handlePipelineStepEnd(ev.data);
          continue;
        }
        if (ev.type === "pipeline_end") {
          handlePipelineEnd();
          continue;
        }
      }
    };
    const es = connectGlobalSSE((event) => {
      if (
        [
          "text_delta",
          "thinking_delta",
          "sub_agent_text_delta",
          "sub_agent_tool_call",
          "sub_agent_tool_result",
        ].includes(event.type)
      )
        return;
      pending.push(event);
      if (!timer)
        timer = setTimeout(() => {
          timer = null;
          flush();
        }, 150);
    });
    esRef.current = es;
    return () => {
      es.close();
      esRef.current = null;
      if (timer) clearTimeout(timer);
    };
  }, [handlePipelineStart, handlePipelineStepEnd, handlePipelineEnd]);

  const activePipes = pipelines.filter((p) => !p.finished);
  const donePipes = pipelines.filter((p) => p.finished).slice(0, 5);
  const selectedProfile =
    selectedAgent && profiles.length > 0
      ? profiles.find((p) => p.name === selectedAgent)
      : null;

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-[var(--bg-primary)]">
      {/* Header */}
      <div className="flex items-center gap-4 px-6 py-3 border-b border-[var(--border)] bg-[var(--bg-secondary)]">
        <span className="text-sm font-semibold tracking-wide text-[var(--text-primary)] font-mono">
          DASHBOARD
        </span>
        <div className="flex-1" />
        <div className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)]">
          <span
            className="w-2 h-2 rounded-full"
            style={{
              background:
                activePipes.length > 0
                  ? colors.success
                  : colors.textTertiary,
              boxShadow:
                activePipes.length > 0
                  ? `0 0 8px ${colors.success}66`
                  : "none",
            }}
          />
          <span className="font-mono">
            {activePipes.length > 0
              ? `${activePipes.length} pipeline${activePipes.length > 1 ? "s" : ""} running`
              : "All clear"}
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-5 flex flex-col gap-6">
        {/* ─── Agent Cards ─── */}
        <section>
          <SectionLabel>
            <span className="flex items-center gap-1.5">
              <Activity size={11} />
              AGENTS
            </span>
          </SectionLabel>
          {profiles.length === 0 ? (
            <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] py-10 text-center text-xs text-[var(--text-tertiary)]">
              No agent profiles loaded.
            </div>
          ) : (
            <div
              className="grid gap-3"
              style={{
                gridTemplateColumns:
                  "repeat(auto-fill, minmax(210px, 1fr))",
              }}
            >
              {profiles.map((p) => {
                const running = runningCounts[p.name] || 0;
                const active = running > 0;
                const accent = agentColor(p.name, colors);
                const accentBg = agentBgVar(p.name);
                const accentBorder = agentBorderVar(p.name);
                return (
                  <div
                    key={p.name}
                    className={cn(
                      "rounded-xl p-4 cursor-pointer transition-all duration-200",
                      "border bg-[var(--bg-secondary)] hover:brightness-110",
                    )}
                    style={{
                      borderColor: active
                        ? accentBorder
                        : "var(--border)",
                      boxShadow: active
                        ? `0 0 16px ${accent}26`
                        : "none",
                    }}
                    onClick={() =>
                      setSelectedAgent(
                        selectedAgent === p.name ? null : p.name,
                      )
                    }
                  >
                    <div className="flex items-center justify-between mb-2.5">
                      <div className="flex items-center gap-2.5">
                        <div
                          className="w-8 h-8 rounded-lg flex items-center justify-center text-lg"
                          style={{ background: accentBg }}
                        >
                          {p.icon}
                        </div>
                        <div>
                          <div className="text-sm font-semibold text-[var(--text-primary)]">
                            {p.display_name}
                          </div>
                          <div
                            className="text-xs font-mono"
                            style={{ color: accent }}
                          >
                            {p.name}
                          </div>
                        </div>
                      </div>
                      {active ? (
                        <div
                          className="flex items-center gap-1.5 px-2 py-0.5 rounded-full"
                          style={{ background: accentBg }}
                        >
                          <span
                            className="w-2 h-2 rounded-full"
                            style={{
                              background: accent,
                              boxShadow: `0 0 6px ${accent}`,
                              animation:
                                "pulse 1.5s ease-in-out infinite",
                            }}
                          />
                          <span
                            className="text-xs font-bold"
                            style={{ color: accent }}
                          >
                            {running}
                          </span>
                        </div>
                      ) : (
                        <div className="px-2 py-0.5 rounded-full bg-[var(--bg-tertiary)]">
                          <span className="text-xs text-[var(--text-tertiary)]">
                            idle
                          </span>
                        </div>
                      )}
                    </div>
                    <div className="text-xs leading-relaxed text-[var(--text-tertiary)]">
                      {p.goal.length > 80
                        ? p.goal.slice(0, 80) + "..."
                        : p.goal}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* ─── Active Pipelines ─── */}
        {activePipes.length > 0 && (
          <section>
            <SectionLabel>
              <span className="flex items-center gap-1.5">
                <PlayCircle size={11} />
                ACTIVE PIPELINES
              </span>
            </SectionLabel>
            <div className="flex flex-col gap-3">
              {activePipes.map((p) => (
                <PipelineCard
                  key={p.pipelineId}
                  pipeline={p}
                  colors={colors}
                />
              ))}
            </div>
          </section>
        )}

        {/* ─── History ─── */}
        {donePipes.length > 0 && (
          <section>
            <button
              className="flex items-center gap-2 cursor-pointer mb-3 bg-transparent border-none p-0"
              onClick={() => setHistoryExpanded(!historyExpanded)}
            >
              <HistoryIcon
                size={12}
                className="text-[var(--text-tertiary)]"
              />
              <span className="text-xs font-medium tracking-widest text-[var(--text-tertiary)] font-mono">
                HISTORY ({donePipes.length})
              </span>
              <ChevronRight
                size={12}
                className={cn(
                  "text-[var(--text-tertiary)] transition-transform",
                  historyExpanded && "rotate-90",
                )}
              />
            </button>
            {historyExpanded && (
              <div className="flex flex-col gap-2">
                {donePipes.map((p) => (
                  <PipelineCard
                    key={p.pipelineId}
                    pipeline={p}
                    colors={colors}
                  />
                ))}
              </div>
            )}
          </section>
        )}

        {/* ─── Empty state ─── */}
        {pipelines.length === 0 && profiles.length > 0 && (
          <section className="rounded-2xl border border-[var(--border)] bg-[var(--bg-secondary)] py-14 px-4 flex flex-col items-center text-center">
            <Activity
              size={36}
              className="text-[var(--text-tertiary)] mb-3"
            />
            <div className="text-sm font-medium text-[var(--text-secondary)] mb-1">
              No pipeline activity yet
            </div>
            <div className="text-xs text-[var(--text-tertiary)] max-w-sm leading-relaxed">
              Trigger a multi-agent delegation from chat to see live pipeline
              orchestration here.
            </div>
          </section>
        )}
      </div>

      <Modal
        open={!!selectedProfile}
        onOpenChange={(o) => !o && setSelectedAgent(null)}
        title={
          selectedProfile ? (
            <div className="flex items-center gap-2.5">
              <span
                className="w-9 h-9 rounded-lg flex items-center justify-center text-xl"
                style={{ background: agentBgVar(selectedProfile.name) }}
              >
                {selectedProfile.icon}
              </span>
              <div className="flex flex-col">
                <span>{selectedProfile.display_name}</span>
                <span
                  className="text-[10px] font-mono font-normal"
                  style={{ color: agentColor(selectedProfile.name, colors) }}
                >
                  {selectedProfile.name}
                </span>
              </div>
            </div>
          ) : (
            "Agent"
          )
        }
        size="lg"
        hideClose={false}
      >
        {selectedProfile && (
          <div className="space-y-4">
            <p className="text-xs leading-relaxed text-[var(--text-secondary)] px-1">
              {selectedProfile.goal}
            </p>
            <AgentGrowthChart
              agentName={selectedProfile.name}
              displayName={selectedProfile.display_name}
            />
          </div>
        )}
      </Modal>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 mb-3">
      <span className="text-xs font-semibold tracking-widest text-[var(--text-tertiary)] font-mono">
        {children}
      </span>
      <div className="flex-1 h-px bg-[var(--border)]" />
    </div>
  );
}

function StepIcon({
  status,
  color,
}: {
  status: PipelineStep["status"];
  color: string;
}) {
  if (status === "running") {
    return (
      <span
        className="inline-block w-2 h-2 rounded-full"
        style={{
          background: color,
          boxShadow: `0 0 6px ${color}`,
          animation: "pulse 1.5s ease-in-out infinite",
        }}
      />
    );
  }
  if (status === "done") return <Check size={12} style={{ color }} />;
  if (status === "error") return <XIcon size={12} style={{ color }} />;
  return <Circle size={8} style={{ color }} />;
}

function PipelineCard({
  pipeline,
  colors,
}: {
  pipeline: PipelineState;
  colors: ThemeColors;
}) {
  const [expanded, setExpanded] = useState(!pipeline.historical);
  const total = pipeline.totalSteps;
  const done = pipeline.completedCount;
  const fail = pipeline.failedCount;
  const pct = total > 0 ? done / total : 0;
  const isDone = pipeline.finished;
  const allDone = isDone && fail === 0;

  const ringColor = allDone
    ? colors.success
    : fail > 0
      ? colors.danger
      : colors.accent;
  const statusText = allDone
    ? "Complete"
    : fail > 0
      ? `${fail} failed`
      : `${done}/${total} steps`;

  return (
    <div
      className="rounded-xl overflow-hidden bg-[var(--bg-secondary)] border"
      style={{
        borderColor: isDone ? "var(--border)" : `${ringColor}40`,
        boxShadow: isDone ? "none" : `0 0 16px ${ringColor}1a`,
      }}
    >
      <div
        className="flex items-center justify-between px-4 py-3 cursor-pointer hover:brightness-110 transition-all"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3.5">
          <div className="relative shrink-0 w-9 h-9">
            <svg width="36" height="36" viewBox="0 0 36 36">
              <circle
                cx="18"
                cy="18"
                r="14"
                fill="none"
                stroke="var(--bg-tertiary)"
                strokeWidth="2.5"
              />
              <circle
                cx="18"
                cy="18"
                r="14"
                fill="none"
                stroke={ringColor}
                strokeWidth="2.5"
                strokeDasharray={`${pct * 87.96} 87.96`}
                strokeLinecap="round"
                transform="rotate(-90 18 18)"
                style={{
                  transition: "stroke-dasharray 0.4s ease",
                  filter: `drop-shadow(0 0 3px ${ringColor}66)`,
                }}
              />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">
              <span
                className="font-bold font-mono text-[var(--text-primary)]"
                style={{ fontSize: 10 }}
              >
                {done}/{total}
              </span>
            </div>
          </div>
          <div>
            <div className="text-sm font-medium text-[var(--text-primary)]">
              {isDone ? "Pipeline" : "Running Pipeline"}
            </div>
            <div
              className="text-xs mt-0.5"
              style={{
                color: isDone ? "var(--text-tertiary)" : ringColor,
              }}
            >
              {statusText}
            </div>
          </div>
        </div>
        <ChevronDown
          size={14}
          className={cn(
            "text-[var(--text-tertiary)] transition-transform",
            expanded && "rotate-180",
          )}
        />
      </div>

      {expanded && (
        <div className="px-4 pb-3 pt-1">
          <div className="flex flex-col gap-1">
            {pipeline.steps.map((step) => {
              const accent = agentColor(step.agentName, colors);
              const accentBg = agentBgVar(step.agentName);
              const stepColor =
                step.status === "done"
                  ? colors.success
                  : step.status === "error"
                    ? colors.danger
                    : step.status === "running"
                      ? accent
                      : colors.textTertiary;
              const stepBg =
                step.status === "pending"
                  ? "transparent"
                  : step.status === "running"
                    ? accentBg
                    : step.status === "done"
                      ? "var(--success-bg)"
                      : "var(--danger-bg)";
              return (
                <div
                  key={step.id}
                  className="flex items-center gap-2 px-3 py-2 rounded-lg"
                  style={{ background: stepBg }}
                >
                  <div className="w-5 flex justify-center shrink-0">
                    <StepIcon status={step.status} color={stepColor} />
                  </div>
                  <div
                    className="w-6 h-6 rounded flex items-center justify-center text-[10px] shrink-0 font-bold"
                    style={{ background: accentBg, color: accent }}
                  >
                    {step.agentName.slice(0, 2).toUpperCase()}
                  </div>
                  <span
                    className="text-xs font-medium shrink-0 font-mono"
                    style={{ color: accent, minWidth: 65 }}
                  >
                    {step.agentName}
                  </span>
                  <span className="text-xs truncate flex-1 text-[var(--text-secondary)]">
                    {step.task.slice(0, 50)}
                  </span>
                  {step.status === "done" && step.elapsed != null && (
                    <span className="text-xs shrink-0 tabular-nums font-mono text-[var(--text-tertiary)]">
                      {step.elapsed.toFixed(1)}s
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

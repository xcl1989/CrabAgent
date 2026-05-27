import { useState, useEffect, useCallback, useRef } from "react";
import { connectGlobalSSE, GlobalSSEEvent } from "../api/monitor";
import { listAgentProfiles, AgentProfile, getPipelineHistory, PipelineHistoryItem } from "../api/agents";
import AgentGrowthChart from "../components/AgentGrowthChart";

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

const AGENT_THEME: Record<string, { gradient: string; border: string; glow: string; text: string; bg: string; pulse: string }> = {
  researcher: { gradient: "linear-gradient(135deg, #1e3a5f 0%, #0d1117 100%)", border: "#2563eb", glow: "0 0 20px rgba(37,99,235,0.15)", text: "#60a5fa", bg: "#1e3a5f", pulse: "#3b82f6" },
  analyst:    { gradient: "linear-gradient(135deg, #2d1b4e 0%, #0d1117 100%)", border: "#7c3aed", glow: "0 0 20px rgba(124,58,237,0.15)", text: "#a78bfa", bg: "#2d1b4e", pulse: "#8b5cf6" },
  coder:      { gradient: "linear-gradient(135deg, #0f2918 0%, #0d1117 100%)", border: "#16a34a", glow: "0 0 20px rgba(22,163,74,0.15)", text: "#4ade80", bg: "#0f2918", pulse: "#22c55e" },
  writer:     { gradient: "linear-gradient(135deg, #3b2507 0%, #0d1117 100%)", border: "#d97706", glow: "0 0 20px rgba(217,119,6,0.15)", text: "#fbbf24", bg: "#3b2507", pulse: "#f59e0b" },
};

function getAgentTheme(name: string) {
  return AGENT_THEME[name] || { gradient: "linear-gradient(135deg, #1e293b 0%, #0d1117 100%)", border: "#475569", glow: "none", text: "#94a3b8", bg: "#1e293b", pulse: "#64748b" };
}

const STEP_DOT: Record<string, { icon: string; color: string; bg: string }> = {
  pending:  { icon: "○", color: "#475569", bg: "transparent" },
  running:  { icon: "●", color: "#60a5fa", bg: "rgba(96,165,250,0.08)" },
  done:     { icon: "✓", color: "#4ade80", bg: "rgba(74,222,128,0.06)" },
  error:    { icon: "✗", color: "#f87171", bg: "rgba(248,113,113,0.06)" },
};

export default function DashboardPage() {
  const [profiles, setProfiles] = useState<AgentProfile[]>([]);
  const [runningCounts, setRunningCounts] = useState<Record<string, number>>({});
  const [pipelines, setPipelines] = useState<PipelineState[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [historyExpanded, setHistoryExpanded] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    listAgentProfiles().then(setProfiles).catch(() => {});
    getPipelineHistory(10).then((items) => {
      if (!items.length) return;
      const hist: PipelineState[] = items.map((p) => {
        const isFinished = p.status === "completed" || p.status === "interrupted" || p.status === "failed";
        return {
          pipelineId: String(p.id),
          sessionId: p.session_id || "",
          totalSteps: p.steps?.length || (p.metadata?.total_steps as number) || 0,
          steps: (p.steps || []).map((s) => ({
            id: String(s.id),
            agentName: s.agent_name,
            task: s.task_summary?.slice(0, 200) || "",
            status: (s.status === "completed" ? "done" : s.status === "failed" || s.status === "interrupted" ? "error" : s.status === "running" ? "running" : "pending") as PipelineStep["status"],
            elapsed: s.elapsed || undefined,
            resultSummary: s.result_summary?.slice(0, 300) || undefined,
          })),
          completedCount: (p.steps || []).filter((s) => s.status === "completed").length,
          failedCount: (p.steps || []).filter((s) => s.status === "failed" || s.status === "interrupted").length,
          finished: isFinished,
          historical: isFinished,
          createdAt: p.started_at ? p.started_at * 1000 : Date.now(),
        };
      });
      // Populate runningCounts for active pipelines from API
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
    }).catch(() => {});
  }, []);

  const handlePipelineStart = useCallback((data: Record<string, unknown>, sid: string) => {
    const stepIds = (data.step_ids as string[]) || [];
    const stepAgents = (data.step_agents as Record<string, string>) || {};
    const stepTasks = (data.step_tasks as Record<string, string>) || {};
    const pid = data.pipeline_run_id ? String(data.pipeline_run_id) : Date.now().toString();

    setPipelines((prev) => {
      const filtered = prev.filter((p) => p.finished || p.sessionId !== sid || p.pipelineId === pid);
      if (filtered.some((p) => p.pipelineId === pid)) return filtered;
      return [{
        pipelineId: pid, sessionId: sid,
        totalSteps: (data.total_steps as number) || stepIds.length,
        steps: stepIds.map((id) => ({ id, agentName: stepAgents[id] || "unknown", task: stepTasks[id] || "", status: "pending" as const })),
        completedCount: 0, failedCount: 0, finished: false, createdAt: Date.now(),
      }, ...filtered];
    });

    const counts: Record<string, number> = {};
    for (const id of stepIds) { const n = stepAgents[id] || "unknown"; counts[n] = (counts[n] || 0) + 1; }
    setRunningCounts((prev) => { const next = { ...prev }; for (const [n, c] of Object.entries(counts)) next[n] = (next[n] || 0) + c; return next; });
  }, []);

  const handlePipelineStepEnd = useCallback((data: Record<string, unknown>) => {
    const stepId = data.step_id as string;
    if (!stepId) return;
    setPipelines((prev) => prev.map((p) => {
      if (p.finished || p.historical) return p;
      const step = p.steps.find((s) => s.id === stepId);
      if (step) setRunningCounts((prev) => ({ ...prev, [step.agentName]: Math.max(0, (prev[step.agentName] || 0) - 1) }));
      return {
        ...p,
        steps: p.steps.map((s) => s.id === stepId ? { ...s, status: "done" as const, elapsed: data.elapsed as number, resultSummary: (data.result as string)?.slice(0, 300) } : s),
        completedCount: p.completedCount + 1,
      };
    }));
  }, []);

  const handlePipelineEnd = useCallback(() => {
    setPipelines((prev) => prev.map((p) => p.finished || p.historical ? p : { ...p, finished: true }));
    setRunningCounts({});
  }, []);

  useEffect(() => {
    let pending: GlobalSSEEvent[] = [];
    let timer: ReturnType<typeof setTimeout> | null = null;
    const flush = () => {
      if (!pending.length) return;
      const batch = pending; pending = [];
      for (const ev of batch) {
        const sid = ev.data.session_id as string | undefined || "";
        if (ev.type === "pipeline_start") { handlePipelineStart(ev.data, sid); continue; }
        if (ev.type === "pipeline_step_start") {
          setPipelines((prev) => prev.map((p) => p.finished || p.historical ? p : { ...p, steps: p.steps.map((s) => s.id === ev.data.step_id ? { ...s, status: "running" as const } : s) }));
          continue;
        }
        if (ev.type === "pipeline_step_end") { handlePipelineStepEnd(ev.data); continue; }
        if (ev.type === "pipeline_end") { handlePipelineEnd(); continue; }
      }
    };
    const es = connectGlobalSSE((event) => {
      if (["text_delta", "thinking_delta", "sub_agent_text_delta", "sub_agent_tool_call", "sub_agent_tool_result"].includes(event.type)) return;
      pending.push(event);
      if (!timer) timer = setTimeout(() => { timer = null; flush(); }, 150);
    });
    esRef.current = es;
    return () => { es.close(); esRef.current = null; if (timer) clearTimeout(timer); };
  }, [handlePipelineStart, handlePipelineStepEnd, handlePipelineEnd]);

  const activePipes = pipelines.filter((p) => !p.finished);
  const donePipes = pipelines.filter((p) => p.finished).slice(0, 5);

  return (
    <div className="flex-1 flex flex-col overflow-hidden" style={{ background: "var(--bg-primary)" }}>
      <div className="flex items-center gap-4 px-6 py-3" style={{ borderBottom: "1px solid var(--border)", background: "var(--bg-secondary)" }}>
        <span className="text-sm font-semibold tracking-wide" style={{ color: "var(--text-primary)", fontFamily: "'SF Mono', monospace" }}>DASHBOARD</span>
        <div className="flex-1" />
        <div className="flex items-center gap-1.5 text-xs" style={{ color: "var(--text-tertiary)" }}>
          <div className="w-2 h-2 rounded-full" style={{ background: activePipes.length > 0 ? "#4ade80" : "#475569", boxShadow: activePipes.length > 0 ? "0 0 8px rgba(74,222,128,0.4)" : "none" }} />
          <span style={{ fontFamily: "'SF Mono', monospace" }}>{activePipes.length > 0 ? `${activePipes.length} pipeline${activePipes.length > 1 ? "s" : ""} running` : "All clear"}</span>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-5 flex flex-col gap-6">
        {/* ─── Agent Cards ─── */}
        <section>
          <SectionLabel>AGENTS</SectionLabel>
          <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))" }}>
            {profiles.map((p) => {
              const theme = getAgentTheme(p.name);
              const running = runningCounts[p.name] || 0;
              const active = running > 0;
              return (
                <div
                  key={p.name}
                  className="rounded-xl p-4 cursor-pointer transition-all duration-200"
                  style={{
                    background: active ? theme.gradient : "var(--bg-secondary)",
                    border: `1px solid ${active ? theme.border + "80" : "var(--border)"}`,
                    boxShadow: active ? theme.glow : "none",
                  }}
                  onClick={() => setSelectedAgent(selectedAgent === p.name ? null : p.name)}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.borderColor = theme.border; (e.currentTarget as HTMLElement).style.boxShadow = theme.glow; }}
                  onMouseLeave={(e) => { if (!active) { (e.currentTarget as HTMLElement).style.borderColor = "var(--border)"; (e.currentTarget as HTMLElement).style.boxShadow = "none"; } }}
                >
                  <div className="flex items-center justify-between mb-2.5">
                    <div className="flex items-center gap-2.5">
                      <div className="w-8 h-8 rounded-lg flex items-center justify-center text-lg" style={{ background: theme.bg }}>
                        {p.icon}
                      </div>
                      <div>
                        <div className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{p.display_name}</div>
                        <div className="text-xs" style={{ color: theme.text, fontFamily: "'SF Mono', monospace" }}>{p.name}</div>
                      </div>
                    </div>
                    {active ? (
                      <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full" style={{ background: theme.bg }}>
                        <div className="w-2 h-2 rounded-full" style={{ background: theme.pulse, boxShadow: `0 0 6px ${theme.pulse}`, animation: "pulse 1.5s ease-in-out infinite" }} />
                        <span className="text-xs font-bold" style={{ color: theme.text }}>{running}</span>
                      </div>
                    ) : (
                      <div className="px-2 py-0.5 rounded-full" style={{ background: "var(--bg-tertiary)" }}>
                        <span className="text-xs" style={{ color: "#475569" }}>idle</span>
                      </div>
                    )}
                  </div>
                  <div className="text-xs leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
                    {p.goal.length > 80 ? p.goal.slice(0, 80) + "..." : p.goal}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* ─── Active Pipelines ─── */}
        {activePipes.length > 0 && (
          <section>
            <SectionLabel>ACTIVE PIPELINES</SectionLabel>
            <div className="flex flex-col gap-3">
              {activePipes.map((p) => <PipelineCard key={p.pipelineId} pipeline={p} />)}
            </div>
          </section>
        )}

        {/* ─── History ─── */}
        {donePipes.length > 0 && (
          <section>
            <button
              className="flex items-center gap-2 cursor-pointer mb-3"
              style={{ background: "none", border: "none", padding: 0 }}
              onClick={() => setHistoryExpanded(!historyExpanded)}
            >
              <span style={{ color: "var(--text-tertiary)", transition: "transform 0.15s", display: "inline-block", transform: historyExpanded ? "rotate(90deg)" : "rotate(0deg)", fontFamily: "'SF Mono', monospace", fontSize: 12 }}>▸</span>
              <span className="text-xs font-medium tracking-widest" style={{ color: "var(--text-tertiary)", fontFamily: "'SF Mono', monospace" }}>
                HISTORY ({donePipes.length})
              </span>
            </button>
            {historyExpanded && (
              <div className="flex flex-col gap-2">
                {donePipes.map((p) => <PipelineCard key={p.pipelineId} pipeline={p} />)}
              </div>
            )}
          </section>
        )}
      </div>

      {selectedAgent && profiles.length > 0 && (
        <AgentDetailModal profile={profiles.find((p) => p.name === selectedAgent)!} onClose={() => setSelectedAgent(null)} />
      )}
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 mb-3">
      <span className="text-xs font-semibold tracking-widest" style={{ color: "var(--text-tertiary)", fontFamily: "'SF Mono', monospace" }}>{children}</span>
      <div className="flex-1 h-px" style={{ background: "var(--border)" }} />
    </div>
  );
}

function PipelineCard({ pipeline }: { pipeline: PipelineState }) {
  const [expanded, setExpanded] = useState(!pipeline.historical);
  const total = pipeline.totalSteps;
  const done = pipeline.completedCount;
  const fail = pipeline.failedCount;
  const pct = total > 0 ? done / total : 0;
  const isDone = pipeline.finished;
  const allDone = isDone && fail === 0;

  const ringColor = allDone ? "#4ade80" : fail > 0 ? "#f87171" : "#60a5fa";
  const statusText = allDone ? "Complete" : fail > 0 ? `${fail} failed` : `${done}/${total} steps`;

  return (
    <div className="rounded-xl overflow-hidden" style={{
      background: "var(--bg-secondary)",
      border: `1px solid ${isDone ? "var(--border)" : ringColor + "40"}`,
      boxShadow: isDone ? "none" : `0 0 16px ${ringColor}10`,
    }}>
      <div className="flex items-center justify-between px-4 py-3 cursor-pointer hover:brightness-110 transition-all" onClick={() => setExpanded(!expanded)}>
        <div className="flex items-center gap-3.5">
          <div className="relative shrink-0" style={{ width: 36, height: 36 }}>
            <svg width="36" height="36" viewBox="0 0 36 36">
              <circle cx="18" cy="18" r="14" fill="none" stroke="var(--bg-tertiary)" strokeWidth="2.5" />
              <circle
                cx="18" cy="18" r="14" fill="none"
                stroke={ringColor} strokeWidth="2.5"
                strokeDasharray={`${pct * 87.96} 87.96`}
                strokeLinecap="round"
                transform="rotate(-90 18 18)"
                style={{ transition: "stroke-dasharray 0.4s ease", filter: `drop-shadow(0 0 3px ${ringColor}60)` }}
              />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="font-bold" style={{ color: "var(--text-primary)", fontSize: 10, fontFamily: "'SF Mono', monospace" }}>{done}/{total}</span>
            </div>
          </div>
          <div>
            <div className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
              {isDone ? "Pipeline" : "Running Pipeline"}
            </div>
            <div className="text-xs mt-0.5" style={{ color: isDone ? "var(--text-tertiary)" : ringColor }}>
              {statusText}
            </div>
          </div>
        </div>
        <span className="text-xs px-1" style={{ color: "var(--text-tertiary)" }}>{expanded ? "▲" : "▼"}</span>
      </div>

      {expanded && (
        <div className="px-4 pb-3 pt-1">
          <div className="flex flex-col gap-1">
            {pipeline.steps.map((step, i) => {
              const dot = STEP_DOT[step.status] || STEP_DOT.pending;
              const theme = getAgentTheme(step.agentName);
              return (
                <div key={step.id} className="flex items-center gap-2 px-3 py-2 rounded-lg" style={{ background: dot.bg || "var(--bg-tertiary)" }}>
                  <div className="w-5 flex justify-center shrink-0">
                    {step.status === "running"
                      ? <div className="w-2 h-2 rounded-full" style={{ background: theme.pulse, boxShadow: `0 0 6px ${theme.pulse}`, animation: "pulse 1.5s ease-in-out infinite" }} />
                      : <span style={{ color: dot.color, fontSize: 11 }}>{dot.icon}</span>
                    }
                  </div>
                  <div className="w-6 h-6 rounded flex items-center justify-center text-xs shrink-0" style={{ background: theme.bg, color: theme.text }}>
                    {step.agentName.slice(0, 2).toUpperCase()}
                  </div>
                  <span className="text-xs font-medium shrink-0" style={{ color: theme.text, fontFamily: "'SF Mono', monospace", minWidth: 65 }}>
                    {step.agentName}
                  </span>
                  <span className="text-xs truncate flex-1" style={{ color: "var(--text-secondary)" }}>
                    {step.task.slice(0, 50)}
                  </span>
                  {step.status === "done" && step.elapsed != null && (
                    <span className="text-xs shrink-0 tabular-nums" style={{ color: "var(--text-tertiary)", fontFamily: "'SF Mono', monospace" }}>
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

function AgentDetailModal({ profile, onClose }: { profile: AgentProfile; onClose: () => void }) {
  const theme = getAgentTheme(profile.name);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.65)", backdropFilter: "blur(4px)" }} onClick={onClose}>
      <div className="rounded-xl w-full max-w-lg mx-4 max-h-[80vh] overflow-auto" style={{ background: "var(--bg-secondary)", border: `1px solid ${theme.border}60`, boxShadow: `0 0 40px ${theme.border}15` }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: "1px solid var(--border)" }}>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg flex items-center justify-center text-xl" style={{ background: theme.bg }}>{profile.icon}</div>
            <div>
              <div className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{profile.display_name}</div>
              <div className="text-xs" style={{ color: theme.text, fontFamily: "'SF Mono', monospace" }}>{profile.name}</div>
            </div>
          </div>
          <button onClick={onClose} className="w-7 h-7 rounded-lg flex items-center justify-center hover:brightness-150 transition-all" style={{ background: "var(--bg-tertiary)", color: "var(--text-tertiary)", border: "none", cursor: "pointer", fontSize: 14 }}>✕</button>
        </div>
        <div className="p-5">
          <p className="text-xs mb-4 px-1" style={{ color: "var(--text-secondary)", lineHeight: 1.7 }}>{profile.goal}</p>
          <AgentGrowthChart agentName={profile.name} displayName={profile.display_name} />
        </div>
      </div>
    </div>
  );
}

import { useState, useEffect, useCallback, useRef } from "react";
import { connectGlobalSSE, getAgentMonitor, AgentMonitorInfo, GlobalSSEEvent } from "../api/monitor";

interface AgentActivity {
  sessionId: string;
  model: string;
  status: string;
  startedAt: number;
  elapsed: number;
  events: ActivityEvent[];
  toolCalls: number;
  currentAction: string;
}

interface ActivityEvent {
  type: string;
  timestamp: number;
  data: Record<string, unknown>;
}

export default function DashboardPage() {
  const [agents, setAgents] = useState<AgentActivity[]>([]);
  const [totalEvents, setTotalEvents] = useState(0);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    getAgentMonitor().then((list) => {
      setAgents((prev) => {
        const map = new Map(prev.map((a) => [a.sessionId, a]));
        for (const a of list) {
          const sid = a.session_id;
          if (!map.has(sid)) {
            map.set(sid, {
              sessionId: sid,
              model: a.model,
              status: a.status,
              startedAt: a.started_at,
              elapsed: a.elapsed,
              events: [],
              toolCalls: 0,
              currentAction: a.status === "running" ? "running" : "idle",
            });
          }
        }
        return Array.from(map.values());
      });
    }).catch(() => {});
  }, []);

  useEffect(() => {
    let evtCount = 0;
    let lastSample = Date.now();
    let pending: GlobalSSEEvent[] = [];
    let timer: ReturnType<typeof setTimeout> | null = null;

    const flush = () => {
      if (pending.length === 0) return;
      const batch = pending;
      pending = [];
      setTotalEvents((c) => c + batch.length);
      setAgents((prev) => {
        let next = [...prev];
        for (const event of batch) {
          const sid = event.data.session_id as string | undefined;
          if (!sid) continue;
          const idx = next.findIndex((a) => a.sessionId === sid);
          const newEvent: ActivityEvent = {
            type: event.type,
            timestamp: event.timestamp || Date.now(),
            data: event.data,
          };
          if (idx >= 0) {
            const agent = next[idx];
            const updatedEvents = [...agent.events.slice(-49), newEvent];
            let updated = { ...agent, events: updatedEvents };
            if (event.type === "tool_call") {
              updated = { ...updated, toolCalls: updated.toolCalls + 1, currentAction: (event.data.name as string) || "" };
            } else if (event.type === "thinking_delta") {
              updated = { ...updated, currentAction: "thinking..." };
            } else if (event.type === "agent_end") {
              updated = { ...updated, status: "done", currentAction: "done" };
            } else if (event.type === "agent_start") {
              updated = { ...updated, status: "running", currentAction: "starting..." };
            } else if (event.type === "sub_agent_tool_call") {
              updated = { ...updated, toolCalls: updated.toolCalls + 1, currentAction: (event.data.name as string) || "" };
            } else if (event.type === "sub_agent_text_delta") {
              const actionText = (event.data.text as string)?.slice(-40) || "...";
              updated = { ...updated, status: "running", currentAction: actionText };
            } else if (event.type === "sub_agent_tool_result") {
              updated = { ...updated, status: "running", currentAction: (event.data.name as string) || "tool result" };
            } else if (event.type === "sub_agent_end") {
              updated = { ...updated, status: "done", currentAction: "done", elapsed: (event.data.elapsed as number) || 0 };
            } else if (event.type === "sub_agent_error") {
              updated = { ...updated, status: "error", currentAction: "error" };
            }
            next = [...next.slice(0, idx), updated, ...next.slice(idx + 1)];
          } else if (event.type === "agent_start") {
            next = [...next, {
              sessionId: sid,
              model: (event.data.model as string) || "",
              status: "running",
              startedAt: Date.now() / 1000,
              elapsed: 0,
              events: [newEvent],
              toolCalls: 0,
              currentAction: "starting...",
            }];
          } else if (event.type === "sub_agent_start") {
            const subId = (event.data.sub_agent_id as string) || "";
            if (!subId) continue;
            next = [...next, {
              sessionId: subId,
              model: (event.data.agent_name as string) || "",
              status: "running",
              startedAt: Date.now() / 1000,
              elapsed: 0,
              events: [newEvent],
              toolCalls: 0,
              currentAction: (event.data.task as string)?.slice(0, 60) || "delegated task",
            }];
          }
        }
        return next;
      });
    };

    const es = connectGlobalSSE((event: GlobalSSEEvent) => {
      evtCount++;
      const now = Date.now();
      if (now - lastSample > 5000) {
        console.log(
          `[Dashboard] ${evtCount} events in ${((now - lastSample) / 1000).toFixed(1)}s`
        );
        evtCount = 0;
        lastSample = now;
      }
      pending.push(event);
      if (!timer) {
        timer = setTimeout(() => {
          timer = null;
          flush();
        }, 200);
      }
    });
    esRef.current = es;
    return () => {
      es.close();
      esRef.current = null;
      if (timer) clearTimeout(timer);
    };
  }, []);

  const running = agents.filter((a) => a.status === "running").length;
  const done = agents.filter((a) => a.status === "done").length;
  const totalTools = agents.reduce((s, a) => s + a.toolCalls, 0);

  return (
    <div className="flex-1 flex flex-col overflow-hidden" style={{ background: "var(--bg-primary)" }}>
      <div
        className="flex items-center gap-6 px-6 py-3"
        style={{ borderBottom: "1px solid var(--border)", background: "var(--bg-secondary)" }}
      >
        <div className="flex items-center gap-2">
          <div
            className="w-2 h-2 rounded-full"
            style={{
              background: running > 0 ? "#34d399" : "var(--text-tertiary)",
              boxShadow: running > 0 ? "0 0 6px #34d399" : "none",
            }}
          />
          <span className="text-sm font-medium" style={{ color: "var(--text-primary)", fontFamily: "'SF Mono', 'Fira Code', monospace" }}>
            AGENT MONITOR
          </span>
        </div>
        <div className="flex items-center gap-4 text-xs" style={{ color: "var(--text-tertiary)", fontFamily: "'SF Mono', monospace" }}>
          <span>
            <span style={{ color: "#34d399" }}>{running}</span> running
          </span>
          <span>
            <span style={{ color: "var(--text-secondary)" }}>{done}</span> done
          </span>
          <span>
            <span style={{ color: "var(--text-secondary)" }}>{agents.length}</span> total
          </span>
          <span>
            <span style={{ color: "var(--text-secondary)" }}>{totalTools}</span> tool calls
          </span>
          <span>
            <span style={{ color: "var(--text-secondary)" }}>{totalEvents}</span> events
          </span>
        </div>
      </div>

      {agents.length === 0 ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <div
              className="text-4xl mb-3"
              style={{ color: "var(--text-tertiary)", fontFamily: "'SF Mono', monospace" }}
            >
              ◇
            </div>
            <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
              No active agents. Send a message in Chat to see live monitoring here.
            </p>
          </div>
        </div>
      ) : (
        <div className="flex-1 overflow-auto p-4">
          <div
            className="grid gap-3"
            style={{
              gridTemplateColumns: `repeat(auto-fill, minmax(380px, 1fr))`,
            }}
          >
            {agents.map((agent) => (
              <AgentMonitorPanel key={agent.sessionId} agent={agent} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function AgentMonitorPanel({ agent }: { agent: AgentActivity }) {
  const isRunning = agent.status === "running";
  const statusColor = isRunning ? "#34d399" : agent.status === "done" ? "var(--text-tertiary)" : "#f87171";

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{
        background: "var(--bg-secondary)",
        border: `1px solid ${isRunning ? "#34d39940" : "var(--border)"}`,
      }}
    >
      <div
        className="flex items-center justify-between px-4 py-2.5"
        style={{ borderBottom: "1px solid var(--border)", background: isRunning ? "#34d39908" : "transparent" }}
      >
        <div className="flex items-center gap-2.5">
          <div
            className="w-1.5 h-1.5 rounded-full"
            style={{
              background: statusColor,
              boxShadow: isRunning ? `0 0 4px ${statusColor}` : "none",
            }}
          />
          <span
            className="text-xs font-medium"
            style={{ color: "var(--text-primary)", fontFamily: "'SF Mono', monospace" }}
          >
            {agent.sessionId.slice(0, 8)}
          </span>
          {agent.model && (
            <span
              className="text-xs px-1.5 py-0.5 rounded"
              style={{ background: "var(--bg-tertiary)", color: "var(--text-tertiary)", fontFamily: "'SF Mono', monospace" }}
            >
              {agent.model.length > 20 ? agent.model.slice(0, 20) + "…" : agent.model}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs" style={{ color: "var(--text-tertiary)", fontFamily: "'SF Mono', monospace" }}>
          <span>{agent.toolCalls} tools</span>
          <span>{isRunning ? formatElapsed(agent.startedAt) : `${agent.elapsed.toFixed(1)}s`}</span>
        </div>
      </div>

      <div className="px-4 py-2" style={{ minHeight: 48 }}>
        {isRunning && (
          <div className="flex items-center gap-2 mb-1.5">
            <div className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: "#34d399" }} />
            <span className="text-xs" style={{ color: "#34d399", fontFamily: "'SF Mono', monospace" }}>
              running
            </span>
          </div>
        )}
        <div
          className="text-xs overflow-auto"
          style={{
            color: "var(--text-tertiary)",
            fontFamily: "'SF Mono', 'Fira Code', monospace",
            maxHeight: 160,
            lineHeight: 1.5,
          }}
        >
          {agent.events.slice(-15).map((e, i) => (
            <div key={i} className="flex gap-2 items-start">
              <span
                className="shrink-0"
                style={{ color: "var(--text-tertiary)", opacity: 0.75, minWidth: "52px" }}
              >
                {new Date(e.timestamp / (e.timestamp > 1e12 ? 1 : 1000) * 1000).toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </span>
              <span className="shrink-0" style={{ color: eventColor(e.type) }}>
                {e.type.replace(/_/g, " ")}
              </span>
              {e.type === "tool_call" && (
                <span style={{ color: "var(--text-secondary)" }}>
                  {(e.data.name as string) || ""}
                </span>
              )}
              {e.type === "sub_agent_tool_call" && (
                <span style={{ color: "var(--text-secondary)" }}>
                  {(e.data.name as string) || ""}
                </span>
              )}
              {e.type === "sub_agent_text_delta" && (
                <span className="truncate" style={{ color: "var(--text-tertiary)", maxWidth: 200 }}>
                  {(e.data.text as string)?.slice(0, 80) || ""}
                </span>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function eventColor(type: string): string {
  if (type === "tool_call" || type === "sub_agent_tool_call") return "#60a5fa";
  if (type === "tool_result" || type === "sub_agent_tool_result") return "#a78bfa";
  if (type === "text_delta" || type === "agent_start" || type === "sub_agent_start") return "#34d399";
  if (type === "agent_end" || type === "sub_agent_end") return "var(--text-tertiary)";
  if (type === "agent_error" || type === "sub_agent_error") return "#f87171";
  if (type === "sub_agent_text_delta") return "#fbbf24";
  return "var(--text-tertiary)";
}

function formatElapsed(startedAt: number): string {
  const elapsed = Math.round(Date.now() / 1000 - startedAt);
  if (elapsed < 60) return `${elapsed}s`;
  const m = Math.floor(elapsed / 60);
  const s = elapsed % 60;
  return `${m}m${s}s`;
}

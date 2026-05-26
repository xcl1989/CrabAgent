import { api } from "./client";

export interface AgentMonitorInfo {
  session_id: string;
  model: string;
  status: string;
  started_at: number;
  elapsed: number;
}

export async function getAgentMonitor(): Promise<AgentMonitorInfo[]> {
  return api.get<AgentMonitorInfo[]>("/agents/monitor");
}

export interface GlobalSSEEvent {
  type: string;
  data: Record<string, unknown>;
  timestamp: number;
}

export function connectGlobalSSE(onEvent: (event: GlobalSSEEvent) => void): EventSource {
  const token = localStorage.getItem("crab_token") || "";
  const url = `/api/events/global?token=${encodeURIComponent(token)}`;
  const es = new EventSource(url);
  es.onmessage = (e) => {
    try {
      const event = JSON.parse(e.data) as GlobalSSEEvent;
      onEvent(event);
    } catch {
      // ignore non-JSON (keepalive, etc.)
    }
  };
  return es;
}

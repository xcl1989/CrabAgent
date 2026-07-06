import { api } from "./client";

export interface AgentMonitorInfo {
  session_id: string;
  model: string;
  status: string;
  started_at: number;
  elapsed: number;
  workspace?: string;
  title?: string;
}

export async function getAgentMonitor(): Promise<AgentMonitorInfo[]> {
  return api.get<AgentMonitorInfo[]>("/agents/monitor");
}

export interface GlobalSSEEvent {
  type: string;
  data: Record<string, unknown>;
  timestamp: number;
}

export interface PipelineStartData {
  total_steps: number;
  step_ids: string[];
  step_agents: Record<string, string>;
  step_tasks: Record<string, string>;
  pipeline_run_id?: number;
}

export interface PipelineStepData {
  step_id: string;
  agent_name: string;
  task?: string;
  result?: string;
  elapsed?: number;
}

export interface PipelineEndData {
  completed: string[];
  failed: string[];
  total: number;
  total_elapsed?: number;
  success_count?: number;
  fail_count?: number;
}

export type PipelineSSEEvent =
  | { type: "pipeline_start"; data: PipelineStartData; timestamp: number }
  | { type: "pipeline_step_start"; data: PipelineStepData; timestamp: number }
  | { type: "pipeline_step_end"; data: PipelineStepData; timestamp: number }
  | { type: "pipeline_end"; data: PipelineEndData; timestamp: number };

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

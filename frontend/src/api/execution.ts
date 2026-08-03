import { api } from "./client";

export interface SpanNode {
  id: number;
  session_id: string;
  run_id: string;
  parent_id: number | null;
  seq: number;
  span_type: "agent_run" | "llm_call" | "tool_call" | "agent_delegate" | "compress";
  name: string;
  agent_name: string;
  source: string;
  provider: string;
  started_at: number;
  duration_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
  cached_tokens: number;
  reasoning_tokens: number;
  status: string;
  summary: string;
  error: string;
  children: SpanNode[];
}

export interface RunSummary {
  run_id: string;
  span_count: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  started_at: number;
  ended_at: number;
  agent_name: string;
}

export function getSessionRuns(sessionId: string) {
  return api.get<{ runs: RunSummary[] }>(
    `/execution/sessions/${encodeURIComponent(sessionId)}/runs`,
  );
}

export function getSessionSpanTrees(sessionId: string) {
  return api.get<{ session_id: string; runs: string[]; trees: Record<string, SpanNode[]> }>(
    `/execution/sessions/${encodeURIComponent(sessionId)}/spans`,
  );
}

export function getRunSpanTree(sessionId: string, runId: string) {
  return api.get<{ session_id: string; run_id: string; tree: SpanNode[]; span_count: number }>(
    `/execution/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/spans`,
  );
}

export interface Insight {
  type: "tool_loop" | "token_hotspot" | "context_bloat" | "tool_errors" | "slow_tools";
  severity: "error" | "warning" | "info";
  title: string;
  detail: string;
  span_ids?: number[];
  span_id?: number;
  run_id?: string;
}

export function getSessionInsights(sessionId: string) {
  return api.get<{ session_id: string; insights: Insight[] }>(
    `/execution/sessions/${encodeURIComponent(sessionId)}/insights`,
  );
}

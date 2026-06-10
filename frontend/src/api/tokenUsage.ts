import { api } from "./client";

export interface TrendPoint {
  date?: string;
  hour?: string;
  prompt_tokens: number;
  cached_tokens: number;
  non_cached_tokens: number;
  completion_tokens: number;
  reasoning_tokens: number;
  total_tokens: number;
}

export interface TokenUsageOverview {
  total_tokens: number;
  prompt_tokens: number;
  cached_tokens: number;
  non_cached_tokens: number;
  completion_tokens: number;
  reasoning_tokens: number;
  cache_hit_rate: number;
  total_calls: number;
  today_tokens: number;
  sessions_count: number;
  hourly: boolean;
  trend: TrendPoint[];
  by_agent: {
    agent_name: string;
    total_tokens: number;
    prompt_tokens: number;
    cached_tokens: number;
    completion_tokens: number;
    calls: number;
  }[];
  by_model: {
    model: string;
    total_tokens: number;
    prompt_tokens: number;
    cached_tokens: number;
    completion_tokens: number;
    calls: number;
  }[];
  /** @deprecated use trend */
  daily: TrendPoint[];
}

export interface WorkspaceUsage {
  workspace: string;
  total_tokens: number;
  calls: number;
}

export interface SessionUsage {
  session_id: string;
  title: string;
  total_tokens: number;
  prompt_tokens: number;
  cached_tokens: number;
  non_cached_tokens: number;
  completion_tokens: number;
  reasoning_tokens: number;
  cache_hit_rate: number;
  calls: number;
  last_active: string;
  created_at: string;
}

export interface SessionUsageDetail {
  session_id: string;
  total: {
    prompt_tokens: number;
    cached_tokens: number;
    non_cached_tokens: number;
    completion_tokens: number;
    reasoning_tokens: number;
    total_tokens: number;
    cache_hit_rate: number;
    calls: number;
  };
  by_agent: {
    agent_name: string;
    prompt_tokens: number;
    cached_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    calls: number;
  }[];
  by_model: {
    model: string;
    prompt_tokens: number;
    cached_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    calls: number;
  }[];
  records: {
    id: number;
    agent_name: string;
    model: string;
    prompt_tokens: number;
    cached_tokens: number;
    non_cached_tokens: number;
    completion_tokens: number;
    reasoning_tokens: number;
    total_tokens: number;
    iteration: number;
    created_at: string;
  }[];
}

export function getOverview(days = 30, workspace = "") {
  return api.get<TokenUsageOverview>("/token-usage/overview", {
    days: String(days),
    ...(workspace ? { workspace } : {}),
  });
}

export function getSessionsUsage(limit = 20, offset = 0, workspace = "") {
  return api.get<{ sessions: SessionUsage[]; total: number }>("/token-usage/sessions", {
    limit: String(limit),
    offset: String(offset),
    ...(workspace ? { workspace } : {}),
  });
}

export function getWorkspacesUsage() {
  return api.get<WorkspaceUsage[]>("/token-usage/workspaces");
}

export function getSessionUsageDetail(sessionId: string) {
  return api.get<SessionUsageDetail>(`/token-usage/sessions/${encodeURIComponent(sessionId)}`);
}

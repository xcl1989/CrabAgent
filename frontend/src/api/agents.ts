import { api } from "./client";

export interface AgentProfile {
  id: number;
  name: string;
  display_name: string;
  role: string;
  goal: string;
  backstory: string;
  model: string;
  allow_delegation: boolean;
  enabled: boolean;
  icon: string;
  is_default: boolean;
  tools: string[];
  tool_permissions: Record<string, string>;
  created_at: string;
}

export interface CreateAgentRequest {
  name: string;
  display_name: string;
  role: string;
  goal: string;
  backstory?: string;
  model?: string;
  icon?: string;
  allow_delegation?: boolean;
  tools?: string[];
  tool_permissions?: Record<string, string>;
}

export interface UpdateAgentRequest {
  display_name?: string;
  role?: string;
  goal?: string;
  backstory?: string;
  model?: string;
  icon?: string;
  allow_delegation?: boolean;
  enabled?: boolean;
  tools?: string[];
  tool_permissions?: Record<string, string>;
}

export function listAgentProfiles(): Promise<AgentProfile[]> {
  return api.get("/agents");
}

export function createAgentProfile(req: CreateAgentRequest): Promise<AgentProfile> {
  return api.post("/agents", req);
}

export function updateAgentProfile(name: string, req: UpdateAgentRequest): Promise<AgentProfile> {
  return api.patch(`/agents/${name}`, req);
}

export function deleteAgentProfile(name: string): Promise<void> {
  return api.del(`/agents/${name}`);
}

export interface AgentMemoryItem {
  key: string;
  category: string;
  content: string;
  importance: number;
  source: string;
  task_category: string;
  access_count: number;
  created_at: string | null;
}

export interface AgentTaskStats {
  total: number;
  success_rate: number;
  avg_elapsed: number;
  avg_tokens: number;
}

export function listLearningAgents(): Promise<string[]> {
  return api.get("/agents/learning-agents");
}

export function listAgentMemory(agent_name: string, limit = 20): Promise<AgentMemoryItem[]> {
  return api.get(`/agents/memory?agent_name=${encodeURIComponent(agent_name)}&limit=${limit}`);
}

export function deleteAgentMemory(key: string): Promise<void> {
  return api.del(`/agents/memory/${encodeURIComponent(key)}`);
}

export function getAgentStats(agent_name: string): Promise<AgentTaskStats> {
  return api.get(`/agents/stats?agent_name=${encodeURIComponent(agent_name)}`);
}

export interface AgentRunSummary {
  id: number;
  user_id: number;
  session_id: string;
  parent_run_id: number | null;
  agent_name: string;
  model: string | null;
  task_summary: string;
  status: string;
  started_at: number;
  finished_at: number | null;
  elapsed: number;
  tokens_used: number;
  iterations: number;
  tool_calls_count: number;
  result_summary: string | null;
  error: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface ToolCallEntry {
  name: string;
  args: unknown;
  started_at: number;
  result_summary: string | null;
  elapsed: number;
}

export interface AgentRunDetail extends AgentRunSummary {
  tool_calls: ToolCallEntry[] | null;
}

export interface GrowthPoint {
  date: string;
  total: number;
  success_count: number;
  success_rate: number;
  avg_elapsed: number;
  avg_tokens: number;
}

export interface AgentRunsParams {
  agent_name?: string;
  status?: string;
  session_id?: string;
  limit?: number;
  offset?: number;
}

export function listAgentRuns(params?: AgentRunsParams): Promise<AgentRunSummary[]> {
  const search = new URLSearchParams();
  if (params?.agent_name) search.set("agent_name", params.agent_name);
  if (params?.status) search.set("status", params.status);
  if (params?.session_id) search.set("session_id", params.session_id);
  if (params?.limit !== undefined) search.set("limit", String(params.limit));
  if (params?.offset !== undefined) search.set("offset", String(params.offset));
  const qs = search.toString();
  return api.get(`/agents/runs${qs ? `?${qs}` : ""}`);
}

export function getAgentRun(runId: number): Promise<AgentRunDetail> {
  return api.get(`/agents/runs/${runId}`);
}

export function getAgentGrowth(agentName: string, days = 30): Promise<GrowthPoint[]> {
  return api.get(`/agents/${encodeURIComponent(agentName)}/growth?days=${days}`);
}

export interface PipelineHistoryItem extends AgentRunDetail {
  steps: AgentRunSummary[];
}

export function getPipelineHistory(limit = 10): Promise<PipelineHistoryItem[]> {
  return api.get(`/agents/pipelines/history?limit=${limit}`);
}

export interface ToolInfo {
  name: string;
  description: string;
  default_permission: "auto" | "confirm";
}

export function listTools(): Promise<ToolInfo[]> {
  return api.get("/agents/tools");
}

export function getDefaultToolPermissions(): Promise<{ tool_permissions: Record<string, string> }> {
  return api.get("/agents/default-tool-permissions");
}

export function setDefaultToolPermissions(tool_permissions: Record<string, string>): Promise<{ tool_permissions: Record<string, string> }> {
  return api.put("/agents/default-tool-permissions", { tool_permissions });
}

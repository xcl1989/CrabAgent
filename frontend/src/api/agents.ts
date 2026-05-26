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

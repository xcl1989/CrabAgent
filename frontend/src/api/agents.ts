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

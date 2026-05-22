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
  created_at: string;
}

export interface UpdateAgentRequest {
  display_name?: string;
  role?: string;
  goal?: string;
  backstory?: string;
  model?: string;
  allow_delegation?: boolean;
  enabled?: boolean;
}

export function listAgentProfiles(): Promise<AgentProfile[]> {
  return api.get("/agents");
}

export function updateAgentProfile(name: string, req: UpdateAgentRequest): Promise<AgentProfile> {
  return api.patch(`/agents/${name}`, req);
}

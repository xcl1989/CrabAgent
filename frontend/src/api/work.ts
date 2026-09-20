import { api } from "./client";

export interface AttentionItem {
  kind: string;
  priority: number;
  message: string;
  detail: string;
  target: {
    type: string;
    task_id?: number;
    request_id?: string;
    session_id?: string;
    view?: string;
    title?: string;
  } | null;
  updated_at: string | null;
}

export interface AttentionSummary {
  status: string;
  message: string;
  priority: number;
  count: number;
  target: AttentionItem["target"];
  groups: Record<string, AttentionItem[]>;
  updated_at: string;
}

export function getAttentionSummary(): Promise<AttentionSummary> {
  return api.get("/work/attention/summary");
}

export interface WorkspaceAttention {
  workspace: string;
  priority: number;
  status: string;
  count: number;
}

export function getAttentionByWorkspace(): Promise<{ workspaces: WorkspaceAttention[] }> {
  return api.get("/work/attention/by-workspace");
}

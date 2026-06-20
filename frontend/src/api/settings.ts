import { api } from "./client";

export function getSettings(): Promise<Record<string, string>> {
  return api.get("/settings");
}

export function updateSettings(data: Record<string, string>): Promise<Record<string, string>> {
  return api.put("/settings", { settings: data });
}

export function testSearxng(url: string): Promise<{ success: boolean; result_count?: number; error?: string }> {
  return api.post("/settings/test-searxng", { url });
}

export function testProxy(proxy: string): Promise<{ success: boolean; latency_ms?: number; ip?: string; error?: string }> {
  return api.post("/settings/test-proxy", { proxy });
}

export interface SkillInfo {
  name: string;
  description: string;
  location: string;
  auxiliary_files: string[];
}

export interface SkillDetail extends SkillInfo {
  content: string;
}

export function getSkills(): Promise<SkillInfo[]> {
  return api.get("/settings/skills");
}

export function getSkillDetail(name: string): Promise<SkillDetail> {
  return api.get(`/settings/skills/${encodeURIComponent(name)}`);
}

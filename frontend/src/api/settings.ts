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

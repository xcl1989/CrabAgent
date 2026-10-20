import { api } from "./client";

export interface PushConfig {
  enabled: boolean;
  provider: "bark" | "ntfy";
  bark_server: string;
  bark_device_key: string;
  ntfy_server: string;
  ntfy_topic: string;
  deep_link_base: string;
  notify_task_done: boolean;
  notify_task_waiting: boolean;
  notify_schedule_result: boolean;
  notify_email_summary: boolean;
  sound: string;
  time_sensitive: boolean;
  saved_at: string;
}

export interface PushStatus {
  enabled: boolean;
  provider: "bark" | "ntfy";
  deep_link_base: string;
  notify_task_done: boolean;
  notify_task_waiting: boolean;
  notify_schedule_result: boolean;
  notify_email_summary: boolean;
  sound: string;
  time_sensitive: boolean;
  configured: boolean;
  config: PushConfig;
  saved_at: string;
}

export function getStatus(): Promise<PushStatus> {
  return api.get("/push/status");
}

export function updateConfig(config: Partial<PushConfig>): Promise<{ success: boolean; config: PushConfig }> {
  return api.put("/push/config", config);
}

export function sendTest(title?: string, body?: string): Promise<{ success: boolean }> {
  return api.post("/push/test", { title, body });
}

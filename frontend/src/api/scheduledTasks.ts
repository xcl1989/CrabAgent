import { api } from "./client";

export interface ScheduledTask {
  id: number;
  name: string;
  prompt: string;
  cron_expression: string;
  model: string;
  enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: string;
  last_error: string;
  last_conversation_id: string;
  created_at: string;
}

export interface CreateScheduledTaskRequest {
  name: string;
  prompt: string;
  cron_expression: string;
  model?: string;
}

export interface UpdateScheduledTaskRequest {
  name?: string;
  prompt?: string;
  cron_expression?: string;
  model?: string;
  enabled?: boolean;
}

export function listScheduledTasks(): Promise<ScheduledTask[]> {
  return api.get("/scheduled-tasks");
}

export function createScheduledTask(req: CreateScheduledTaskRequest): Promise<ScheduledTask> {
  return api.post("/scheduled-tasks", req);
}

export function updateScheduledTask(id: number, req: UpdateScheduledTaskRequest): Promise<ScheduledTask> {
  return api.patch(`/scheduled-tasks/${id}`, req);
}

export function deleteScheduledTask(id: number): Promise<void> {
  return api.del(`/scheduled-tasks/${id}`);
}

export function runScheduledTask(id: number): Promise<{ status: string }> {
  return api.post(`/scheduled-tasks/${id}/run`, {});
}

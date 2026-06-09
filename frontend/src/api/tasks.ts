import { api } from "./client";

export interface Task {
  id: number;
  user_id: number;
  title: string;
  description: string;
  assignee: string;
  deadline: string | null;
  source: string;
  source_ref: string;
  source_session: string;
  project: string;
  status: string;
  priority: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface CreateTaskRequest {
  title: string;
  description?: string;
  assignee?: string;
  deadline?: string;
  source?: string;
  project?: string;
  priority?: string;
}

export interface UpdateTaskRequest {
  title?: string;
  description?: string;
  assignee?: string;
  deadline?: string;
  status?: string;
  priority?: string;
  project?: string;
}

export function listTasks(status = "pending", project = ""): Promise<Task[]> {
  const params = new URLSearchParams();
  if (status !== "all") params.set("status", status);
  if (project) params.set("project", project);
  const qs = params.toString();
  return api.get(`/tasks${qs ? `?${qs}` : ""}`);
}

export function createTask(req: CreateTaskRequest): Promise<Task> {
  return api.post("/tasks", req);
}

export function getTask(id: number): Promise<Task> {
  return api.get(`/tasks/${id}`);
}

export function updateTask(id: number, req: UpdateTaskRequest): Promise<Task> {
  return api.patch(`/tasks/${id}`, req);
}

export function deleteTask(id: number): Promise<void> {
  return api.del(`/tasks/${id}`);
}

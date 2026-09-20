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
  // Trusted work system fields
  owner_type?: string;
  owner_name?: string;
  workspace?: string;
  goal_id?: number | null;
  result_summary?: string;
  warning_summary?: string;
  verification_status?: string;
  active_run_id?: number | null;
  last_run_id?: number | null;
  started_at?: string | null;
  completed_at?: string | null;
  result_viewed_at?: string | null;
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
  workspace?: string;
  goal_id?: number | null;
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

export interface AgentRunInfo {
  id: number;
  user_id: number;
  session_id: string | null;
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
  result_summary: string | null;
  error: string | null;
  task_id?: number | null;
  workspace?: string;
  phase?: string;
  progress_current?: number;
  progress_total?: number;
  interrupted_reason?: string;
  created_at: string;
}

export interface TaskArtifact {
  id: number;
  task_id: number;
  run_id: number | null;
  artifact_type: string;
  name: string;
  path: string;
  mime_type: string;
  action: string;
  status: string;
  external_id: string;
  version: number;
  metadata?: Record<string, unknown> | null;
  created_at: string | null;
}

export interface TaskCheck {
  id: number;
  task_id: number;
  run_id: number | null;
  title: string;
  required: boolean;
  status: string;
  evidence: string;
  verified_at: string | null;
}

export interface TaskEventEntry {
  id: number;
  event_type: string;
  title: string;
  detail: string;
  run_id: number | null;
  created_at: string | null;
}

export interface TaskDetail {
  task: Task;
  active_run: AgentRunInfo | null;
  runs: AgentRunInfo[];
  artifacts: TaskArtifact[];
  recent_events?: TaskEventEntry[];
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

// ── Trusted work system endpoints ────────────────────────────────────

export function getTaskDetail(id: number): Promise<TaskDetail> {
  return api.get(`/tasks/${id}/detail`);
}

export function startTask(id: number): Promise<{ task: Task; run_id: number }> {
  return api.post(`/tasks/${id}/start`, {});
}

export function cancelTask(id: number): Promise<Task> {
  return api.post(`/tasks/${id}/cancel`, {});
}

export function retryTask(id: number): Promise<{ task: Task; run_id: number }> {
  return api.post(`/tasks/${id}/retry`, {});
}

export function markResultViewed(id: number): Promise<Task> {
  return api.post(`/tasks/${id}/mark-result-viewed`, {});
}

export function openTaskArtifact(taskId: number, name: string): Promise<{ status: string; path: string }> {
  return api.post(`/tasks/${taskId}/open-artifact`, { name });
}

export function listTaskChecks(id: number): Promise<TaskCheck[]> {
  return api.get(`/tasks/${id}/checks`);
}

export function getRunChanges(taskId: number, runId: number): Promise<RunChanges> {
  return api.get(`/tasks/${taskId}/runs/${runId}/changes`);
}

export function rollbackRun(taskId: number, runId: number, force = false): Promise<RollbackResult> {
  return api.post(`/tasks/${taskId}/runs/${runId}/rollback`, { force });
}

export interface RunChanges {
  run_id: number;
  task_id: number;
  status: string;
  molt_count: number;
  changes: { file: string; molt_id: string; status: string; changed: boolean }[];
}

export interface RollbackResult {
  status: string;
  restored: string[];
  conflicts: { file: string; reason: string }[];
  skipped_unchanged?: number;
  forced?: boolean;
}

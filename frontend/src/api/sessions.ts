import { api } from "./client";

export interface Session {
  session_id: string;
  title: string;
  workspace: string;
  model: string;
  provider: string;
  agent: string;
  active_branch: string;
  prompt_locale: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface SearchResult {
  session_id: string;
  title: string;
  snippet: string;
  role: string;
  updated_at: string | null;
}

export interface Message {
  id: number;
  sequence: number;
  role: string;
  content: string;
  tool_calls?: unknown;
  tool_call_id?: string;
  name?: string;
  reasoning_content?: string;
  branch_id?: string;
  parent_id?: number | null;
  created_at: string | null;
  compressed?: boolean;
  image_data?: string;
  has_images?: boolean;
}

export interface BranchInfo {
  branch_id: string;
  name: string;
  message_count: number;
  parent_message_id: number;
}

export interface WorkspaceInfo {
  workspace: string;
  session_count: number;
  last_active: string | null;
  hidden: boolean;
  pinned: boolean;
  sort_order: number;
}

export interface WorkspacePreferenceUpdate {
  hidden?: boolean;
  pinned?: boolean;
  sort_order?: number;
  current_workspace?: string;
}

export function listSessions(workspace?: string): Promise<Session[]> {
  const params = workspace ? { workspace } : undefined;
  return api.get("/sessions", params);
}

export function listWorkspaces(): Promise<WorkspaceInfo[]> {
  return api.get("/sessions/workspaces");
}

export function getCurrentWorkspace(): Promise<{ workspace: string }> {
  return api.get("/sessions/current-workspace");
}

export function updateWorkspacePreference(workspace: string, update: WorkspacePreferenceUpdate): Promise<WorkspaceInfo> {
  return api.patch(`/sessions/workspace-preferences/${encodeURIComponent(workspace)}`, update);
}

export function reorderWorkspaces(workspaces: string[]): Promise<WorkspaceInfo[]> {
  return api.put("/sessions/workspace-preferences/reorder", { workspaces });
}

export function createSession(title?: string, workspace?: string): Promise<Session> {
  return api.post("/sessions", { title: title || "", workspace: workspace || "" });
}

export function getSession(sessionId: string): Promise<Session> {
  return api.get(`/sessions/${sessionId}`);
}

export function deleteSession(sessionId: string): Promise<void> {
  return api.del(`/sessions/${sessionId}`);
}

export function getMessages(sessionId: string): Promise<Message[]> {
  // The UI keeps compressed history visible; the backend excludes it when rebuilding LLM context.
  return api.get(`/sessions/${sessionId}/messages?limit=1000&include_compressed=true`);
}

export interface CompressionResult {
  summary: string;
  model: string;
  provider: string;
  original_count: number;
}

export function compressSession(sessionId: string, model: string, provider: string): Promise<CompressionResult> {
  return api.post(`/sessions/${sessionId}/compress`, { model, provider });
}

export function getMessageImages(sessionId: string, messageId: number): Promise<{ images: string[] }> {
  return api.get(`/sessions/${sessionId}/messages/${messageId}/images`);
}

export function sendPrompt(
  sessionId: string,
  message: string,
  model?: string,
  images?: string[],
  agent?: string,
  reasoningEffort?: string,
  provider?: string,
  fileContext?: string,
  workspaceType?: string,
  workMode?: boolean,
): Promise<{ status: string }> {
  return api.post(`/sessions/${sessionId}/prompt`, {
    message, model, provider, images, agent,
    reasoning_effort: reasoningEffort,
    file_context: fileContext || undefined,
    workspace_type: workspaceType || undefined,
    work_mode: workMode || undefined,
  });
}

export function switchAgent(sessionId: string, agent: string): Promise<{ status: string }> {
  return api.post(`/sessions/${sessionId}/agent`, { agent });
}

export function abortSession(sessionId: string): Promise<{ status: string }> {
  return api.post(`/sessions/${sessionId}/abort`, {});
}

export function confirmTool(sessionId: string, confirmId: string, approved: boolean): Promise<{ status: string }> {
  return api.post(`/sessions/${sessionId}/tool-confirm`, { confirm_id: confirmId, approved });
}

export function listBranches(sessionId: string): Promise<BranchInfo[]> {
  return api.get(`/sessions/${sessionId}/branches`);
}

export function createBranch(sessionId: string, messageId: number, name?: string): Promise<{ branch_id: string }> {
  return api.post(`/sessions/${sessionId}/branches`, { message_id: messageId, name });
}

export function switchBranch(sessionId: string, branchId: string): Promise<{ branch_id: string }> {
  return api.post(`/sessions/${sessionId}/branches/switch`, { branch_id: branchId });
}

export interface Molt {
  molt_id: string;
  session_id: string;
  branch_id: string;
  description: string;
  method: string;
  file_count: number;
  created_at: string | null;
  files?: string[];
}

export interface MoltDiff {
  file: string;
  diff: string;
}

export function listMolts(sessionId: string): Promise<Molt[]> {
  return api.get(`/sessions/${sessionId}/molts`);
}

export function getMolt(sessionId: string, moltId: string): Promise<Molt> {
  return api.get(`/sessions/${sessionId}/molts/${moltId}`);
}

export function getMoltDiff(sessionId: string, moltId: string): Promise<{ molt_id: string; diffs: MoltDiff[] }> {
  return api.get(`/sessions/${sessionId}/molts/${moltId}/diff`);
}

export function rollbackMolt(sessionId: string, moltId: string): Promise<{ molt_id: string; restored: number; files: string[] }> {
  return api.post(`/sessions/${sessionId}/molts/${moltId}/rollback`, {});
}

export interface TodoItem {
  id: number;
  task: string;
  done: boolean;
  created_at: string | null;
}

export function listTodos(sessionId: string, filter?: string): Promise<TodoItem[]> {
  const params = filter ? `?filter=${filter}` : "";
  return api.get(`/sessions/${sessionId}/todos${params}`);
}

export function addTodo(sessionId: string, task: string): Promise<TodoItem> {
  return api.post(`/sessions/${sessionId}/todos`, { task });
}

export function markTodoDone(sessionId: string, todoId: number): Promise<void> {
  return api.post(`/sessions/${sessionId}/todos/${todoId}/done`, {});
}

export function deleteTodo(sessionId: string, todoId: number): Promise<void> {
  return api.del(`/sessions/${sessionId}/todos/${todoId}`);
}

export function submitInput(sessionId: string, inputId: string, answer: string): Promise<void> {
  return api.post(`/sessions/${sessionId}/user-input`, { input_id: inputId, answer });
}

export function searchSessions(q: string, workspace?: string): Promise<SearchResult[]> {
  const params: Record<string, string> = { q };
  if (workspace) params.workspace = workspace;
  return api.get(`/sessions/search`, params);
}

import { api } from "./client";

export interface Session {
  session_id: string;
  title: string;
  workspace: string;
  model: string;
  active_branch: string;
  created_at: string | null;
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
}

export interface BranchInfo {
  branch_id: string;
  name: string;
  message_count: number;
  parent_message_id: number;
}

export function listSessions(): Promise<Session[]> {
  return api.get("/sessions");
}

export function createSession(title?: string): Promise<Session> {
  return api.post("/sessions", { title: title || "" });
}

export function getSession(sessionId: string): Promise<Session> {
  return api.get(`/sessions/${sessionId}`);
}

export function deleteSession(sessionId: string): Promise<void> {
  return api.del(`/sessions/${sessionId}`);
}

export function getMessages(sessionId: string): Promise<Message[]> {
  return api.get(`/sessions/${sessionId}/messages?limit=1000`);
}

export function sendPrompt(sessionId: string, message: string, model?: string, images?: string[]): Promise<{ status: string }> {
  return api.post(`/sessions/${sessionId}/prompt`, { message, model, images });
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

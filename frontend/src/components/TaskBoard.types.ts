export type TaskStatus = "running" | "done" | "error";

export interface TaskInfo {
  subId: string;
  agentName: string;
  displayName: string;
  icon: string;
  status: TaskStatus;
  task: string;
  content: string;
  toolCalls: number;
  elapsed?: number;
  tokens?: number;
  iterations?: number;
  error?: string;
  startedAt: number;
}

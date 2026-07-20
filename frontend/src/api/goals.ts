import { api } from "./client";
import { Goal, GoalDraft, GoalStatus } from "../types/Goal";

export function getGoal(sessionId: string): Promise<{ goal: Goal | null }> {
  return api.get(`/sessions/${sessionId}/goal`);
}

export function createGoal(
  sessionId: string,
  draft: GoalDraft & {
    execution_model?: string;
    execution_provider?: string;
    execution_agent?: string;
    reasoning_effort?: string;
  },
): Promise<{ goal: Goal }> {
  return api.post(`/sessions/${sessionId}/goal`, draft);
}

export function updateGoal(
  sessionId: string,
  update: Partial<GoalDraft> & { status?: GoalStatus; evidence?: string; blocker?: string; stop_reason?: string },
): Promise<{ goal: Goal }> {
  return api.patch(`/sessions/${sessionId}/goal`, update);
}

export interface GoalHistoryEvent {
  type: string;
  detail: string;
  data?: Record<string, unknown> | null;
  created_at: string;
}

export interface GoalCheckpoint {
  id: number;
  summary: string;
  next_step: string;
  created_at: string;
}

export function getGoalHistory(sessionId: string): Promise<{
  goal: Goal | null;
  events: GoalHistoryEvent[];
  checkpoints: GoalCheckpoint[];
}> {
  return api.get(`/sessions/${sessionId}/goal/history`);
}

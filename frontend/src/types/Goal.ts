export type GoalStatus = "active" | "paused" | "budget_limited" | "complete" | "unmet" | "cleared";

export interface Goal {
  id: number;
  session_id: string;
  objective: string;
  execution_model: string;
  execution_provider: string;
  execution_agent: string;
  reasoning_effort: string;
  success_criteria: string[];
  constraints: string[];
  status: GoalStatus;
  auto_continue: boolean;
  token_budget: number | null;
  tokens_used: number;
  max_auto_turns: number | null;
  auto_turns: number;
  completion_evidence: string;
  blocker: string;
  latest_checkpoint: string;
  next_step: string;
  stop_reason: string;
  created_at: string | null;
  updated_at: string | null;
  closed_at: string | null;
}

export interface GoalDraft {
  objective: string;
  success_criteria: string[];
  constraints: string[];
  auto_continue: boolean;
  token_budget?: number | null;
  max_auto_turns?: number | null;
}

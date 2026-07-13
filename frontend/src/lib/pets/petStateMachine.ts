/**
 * Standardized pet animation state machine.
 *
 * Maps CrabAgent agent statuses to Codex-compatible animation names and
 * maintains a queue of one-shot interactions (jump / wave) that play over the
 * current looping state.
 */

export type PetAnimationName =
  | "idle"
  | "running-right"
  | "running-left"
  | "waving"
  | "jumping"
  | "failed"
  | "waiting"
  | "running"
  | "review";

export type AgentStatus =
  | "idle"
  | "thinking"
  | "working"
  | "waiting"
  | "error"
  | "completed";

export interface PetState {
  /** The animation row currently being rendered. */
  animation: PetAnimationName;
  /** If true the animation should loop; one-shots return to baseAfter. */
  loop: boolean;
  /** For one-shot animations, the animation to return to when finished. */
  baseAfter: PetAnimationName;
  /** Human-readable label shown in the bubble. */
  label: string;
  /** Human-readable detail shown in the bubble. */
  detail: string;
  /** Optional target session id for click-to-open behavior. */
  targetSessionId: string | null;
}

const AGENT_TO_ANIMATION: Record<AgentStatus, PetAnimationName> = {
  idle: "idle",
  thinking: "running",
  working: "running",
  waiting: "waiting",
  error: "failed",
  completed: "review",
};

const DEFAULT_LABELS: Record<AgentStatus, { label: string; detail: string }> = {
  idle: { label: "CrabAgent", detail: "随时可以开始" },
  thinking: { label: "正在思考", detail: "整理思路中…" },
  working: { label: "正在工作", detail: "处理任务中…" },
  waiting: { label: "需要你处理", detail: "点我打开" },
  error: { label: "遇到一点问题", detail: "点我查看" },
  completed: { label: "任务完成", detail: "做得漂亮！" },
};

export interface StateMachineInput {
  status: AgentStatus;
  message?: string;
  targetSessionId?: string | null;
}

/**
 * Return the canonical pet state for an agent status snapshot.
 *
 * This is deterministic and side-effect free; callers own any debouncing or
 * state-key deduplication to avoid re-renders.
 */
export function derivePetState(input: StateMachineInput): PetState {
  const status = input.status || "idle";
  const animation = AGENT_TO_ANIMATION[status];
  const labels = DEFAULT_LABELS[status];
  return {
    animation,
    loop: true,
    baseAfter: animation,
    label: labels.label,
    detail: input.message || labels.detail,
    targetSessionId: input.targetSessionId ?? null,
  };
}

/**
 * Derive a one-shot interaction state.
 *
 * The renderer should play `animation` once and then automatically transition
 * back to `baseAfter`.
 */
export function oneShotAnimation(
  animation: "waving" | "jumping",
  base: PetAnimationName,
): PetState {
  return {
    animation,
    loop: false,
    baseAfter: base,
    label: "",
    detail: "",
    targetSessionId: null,
  };
}

/** Map drag direction to a directional running animation. */
export function dragDirectionAnimation(deltaX: number): PetAnimationName {
  return deltaX > 0 ? "running-right" : "running-left";
}

/** Compare two pet states for visual equality. */
export function petStateKey(state: PetState): string {
  return `${state.animation}|${state.loop}|${state.label}|${state.detail}|${state.targetSessionId ?? ""}`;
}
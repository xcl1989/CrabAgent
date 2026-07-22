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
  | "review"
  | "thinking"
  | "typing"
  | "reading"
  | "searching"
  | "tool-using"
  | "celebrate"
  | "sleep"
  | "surprised"
  | "confused"
  | "pet";

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
  thinking: "thinking",
  working: "running",
  waiting: "waiting",
  error: "failed",
  completed: "celebrate",
};

const DEFAULT_LABELS: Record<AgentStatus, { label: string; detail: string }> = {
  idle: { label: "", detail: "在线待命，随时可以开始" },
  thinking: { label: "正在思考", detail: "整理思路中…" },
  working: { label: "正在工作", detail: "处理任务中…" },
  waiting: { label: "需要你", detail: "有一件事等你处理，点我打开" },
  error: { label: "遇到一点问题", detail: "点我查看详情" },
  completed: { label: "完成啦", detail: "做得漂亮！" },
};

const TOOL_LABELS: Partial<Record<PetAnimationName, { label: string; detail: string }>> = {
  reading: { label: "正在阅读", detail: "查看资料中…" },
  typing: { label: "正在输入", detail: "编辑内容中…" },
  searching: { label: "正在搜索", detail: "检索资料中…" },
  "tool-using": { label: "正在操作工具", detail: "执行任务中…" },
};

export interface StateMachineInput {
  status: AgentStatus;
  message?: string;
  toolName?: string;
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
  const toolDriven = status === "thinking" || status === "working";
  const animation = (toolDriven ? toolAnimation(input.toolName) : null) ?? AGENT_TO_ANIMATION[status];
  const labels = TOOL_LABELS[animation] ?? DEFAULT_LABELS[status];
  return {
    animation,
    loop: true,
    baseAfter: animation,
    label: labels.label,
    detail: input.message || labels.detail,
    targetSessionId: input.targetSessionId ?? null,
  };
}

/** Resolve an optional tool name into a more expressive work animation. */
export function toolAnimation(toolName?: string): PetAnimationName | null {
  if (!toolName) return null;
  const tool = toolName.toLowerCase();
  if (["read", "glob", "grep", "office_read"].includes(tool)) return "reading";
  if (["write", "edit", "office_edit"].includes(tool)) return "typing";
  if (["web_search", "web_scrape", "browser"].includes(tool)) return "searching";
  if (["bash", "sandbox", "office_create"].includes(tool)) return "tool-using";
  return null;
}

/** Return an available animation or its compatible fallback. */
export function resolveAnimation(
  requested: PetAnimationName,
  available: Record<string, unknown>,
): PetAnimationName {
  const fallbacks: Partial<Record<PetAnimationName, PetAnimationName>> = {
    thinking: "running", typing: "running", reading: "running", searching: "running",
    "tool-using": "running", celebrate: "review", sleep: "idle", surprised: "waiting",
    confused: "failed", pet: "waving",
  };
  let candidate: PetAnimationName | undefined = requested;
  while (candidate) {
    if (available[candidate]) return candidate;
    candidate = fallbacks[candidate];
  }
  return "idle";
}

/**
 * Derive a one-shot interaction state.
 *
 * The renderer should play `animation` once and then automatically transition
 * back to `baseAfter`.
 */
export function oneShotAnimation(
  animation: "waving" | "jumping" | "pet",
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
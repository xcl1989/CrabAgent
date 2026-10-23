// Token/output deltas do not change the monitor's state band.
const MONITOR_EVENTS = new Set([
  "agent_start", "agent_end", "agent_error", "tool_call", "tool_result",
  "tool_confirm_request", "user_input_request", "request_resolved",
  "sub_agent_start", "sub_agent_end", "sub_agent_error",
  "task_created", "task_updated",
]);

export function affectsMonitor(type: string): boolean {
  return MONITOR_EVENTS.has(type);
}

// Coalesce bursts without starving updates during a continuous event stream.
export function createMonitorRefresh(run: () => void, intervalMs = 2000) {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let lastRun: number | null = null;
  let disposed = false;
  return {
    request() {
      if (disposed || timer !== null) return;
      const delay = lastRun === null ? 0 : Math.max(0, intervalMs - (Date.now() - lastRun));
      timer = setTimeout(() => {
        timer = null;
        lastRun = Date.now();
        run();
      }, delay);
    },
    dispose() {
      disposed = true;
      if (timer !== null) clearTimeout(timer);
      timer = null;
    },
  };
}

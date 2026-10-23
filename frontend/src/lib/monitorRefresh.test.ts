import { afterEach, expect, it, vi } from "vitest";
import { affectsMonitor, createMonitorRefresh } from "./monitorRefresh";

afterEach(() => vi.useRealTimers());

it("ignores streaming deltas but accepts lifecycle and attention events", () => {
  for (const type of ["text_delta", "thinking_delta", "bash_output", "doc_op_delta", "sub_agent_text_delta"]) {
    expect(affectsMonitor(type)).toBe(false);
  }
  for (const type of ["agent_end", "tool_call", "task_updated", "user_input_request", "request_resolved"]) {
    expect(affectsMonitor(type)).toBe(true);
  }
});

it("bounds continuous SSE bursts and polling to one refresh every two seconds", () => {
  vi.useFakeTimers();
  const run = vi.fn();
  const scheduler = createMonitorRefresh(run);
  for (let i = 0; i < 100; i++) {
    scheduler.request();
    vi.advanceTimersByTime(100);
  }
  expect(run).toHaveBeenCalledTimes(6);
  scheduler.dispose();
  vi.runAllTimers();
  expect(run).toHaveBeenCalledTimes(6);
});

it("cancels trailing work on unmount", () => {
  vi.useFakeTimers();
  const run = vi.fn();
  const scheduler = createMonitorRefresh(run);
  scheduler.request();
  scheduler.dispose();
  scheduler.request();
  vi.runAllTimers();
  expect(run).not.toHaveBeenCalled();
});

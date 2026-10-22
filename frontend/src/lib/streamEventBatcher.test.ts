import { afterEach, describe, expect, it, vi } from "vitest";
import { createStreamEventBatcher } from "./streamEventBatcher";
import type { SSEEvent } from "../api/events";

const event = (type: string, text = ""): SSEEvent => ({ type, data: { text }, timestamp: 1 });
afterEach(() => vi.useRealTimers());

describe("stream event batching", () => {
  it("coalesces rapid deltas without modifying the source event", () => {
    vi.useFakeTimers();
    const deliver = vi.fn();
    const batch = createStreamEventBatcher(deliver);
    const first = event("text_delta", "a");
    batch.push(first);
    for (let i = 0; i < 99; i++) batch.push(event("text_delta", "b"));
    expect(deliver).not.toHaveBeenCalled();
    vi.advanceTimersByTime(50);
    expect(deliver).toHaveBeenCalledTimes(1);
    expect(deliver.mock.calls[0][0].data.text).toBe("a" + "b".repeat(99));
    expect(first.data.text).toBe("a");
  });

  it("preserves ordering around tools, thinking and completion", () => {
    vi.useFakeTimers();
    const events: SSEEvent[] = [];
    const batch = createStreamEventBatcher((e) => events.push(e));
    for (const type of ["thinking_delta", "text_delta", "tool_call", "bash_output", "tool_result", "agent_end"]) {
      batch.push(event(type, type));
    }
    vi.runAllTimers();
    expect(events.map((e) => e.type)).toEqual([
      "thinking_delta", "text_delta", "tool_call", "bash_output", "tool_result", "agent_end",
    ]);
  });

  it("drops pending old-session events on disconnect", () => {
    vi.useFakeTimers();
    const deliver = vi.fn();
    const batch = createStreamEventBatcher(deliver);
    batch.push(event("text_delta", "old session"));
    batch.clear();
    vi.runAllTimers();
    expect(deliver).not.toHaveBeenCalled();
    batch.push(event("text_delta", "new session"));
    vi.advanceTimersByTime(50);
    expect(deliver.mock.calls[0][0].data.text).toBe("new session");
  });

  it("does not merge different speakers or tool output streams", () => {
    vi.useFakeTimers();
    const deliver = vi.fn();
    const batch = createStreamEventBatcher(deliver);
    batch.push({ ...event("bash_output", "a"), data: { text: "a", tool_call_id: "1" } });
    batch.push({ ...event("bash_output", "b"), data: { text: "b", tool_call_id: "2" } });
    vi.runAllTimers();
    expect(deliver).toHaveBeenCalledTimes(2);
  });
});

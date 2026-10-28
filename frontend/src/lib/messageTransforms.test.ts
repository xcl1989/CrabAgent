import { describe, expect, it } from "vitest";
import { SSEEvent } from "../api/events";
import { ChatMessage } from "../types/ChatMessage";
import { sseEventToMessages } from "./messageTransforms";

function resultCard(runId: number): ChatMessage {
  return {
    id: `result-${runId}`,
    role: "task_result",
    content: "生成报告",
    task_result: {
      task_id: 9,
      title: "生成报告",
      status: "done",
      run_id: runId,
    },
  };
}

function taskEvent(runId: number, summary: string): SSEEvent {
  return {
    type: "task_updated",
    timestamp: Date.now(),
    data: {
      task_id: 9,
      title: "生成报告",
      status: "done",
      run_id: runId,
      result_summary: summary,
    },
  } as SSEEvent;
}

describe("task result cards", () => {
  it("adds one card for each completion run", () => {
    const messages = [resultCard(101)];
    const updated = sseEventToMessages(taskEvent(202, "V2"), messages);

    expect(updated).toHaveLength(2);
    expect(updated[1].task_result?.run_id).toBe(202);
  });

  it("updates the matching run instead of duplicating it", () => {
    const messages = [resultCard(101), resultCard(202)];
    const updated = sseEventToMessages(taskEvent(202, "V2 verified"), messages);

    expect(updated).toHaveLength(2);
    expect(updated[1].task_result?.result_summary).toBe("V2 verified");
  });
});

describe("bash stream correlation", () => {
  const calls: ChatMessage[] = ["one", "two"].map((id) => ({
    id: `tc-${id}`, role: "tool_call", tool_call_id: id,
    content: JSON.stringify({ name: "bash", arguments: {} }),
  }));
  it("routes chunks to the matching call instead of the most recent bash", () => {
    const updated = sseEventToMessages({ type: "bash_output", timestamp: 0, data: { text: "first", tool_call_id: "one" } }, calls);
    expect(updated[0].bashStream).toBe("first");
    expect(updated[1].bashStream).toBeUndefined();
    expect(calls[0].bashStream).toBeUndefined();
  });
  it("does not route an unknown call to a different terminal", () => {
    const updated = sseEventToMessages({ type: "bash_output", timestamp: 0, data: { text: "lost", tool_call_id: "missing" } }, calls);
    expect(updated.every((call) => !call.bashStream)).toBe(true);
  });
});

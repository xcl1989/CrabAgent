import { describe, expect, it } from "vitest";
import { SSEEvent } from "../api/events";
import { ChatMessage } from "../types/ChatMessage";
import { dbMessagesToChat, sseEventToMessages } from "./messageTransforms";

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

describe("memory reference cards", () => {
  it("shows only nonempty receipts and deduplicates by user anchor", () => {
    const event = (keys: string[]): SSEEvent => ({
      type: "memory_references", timestamp: 0, data: { anchor_id: 42, keys },
    });
    expect(sseEventToMessages(event([]), [])).toEqual([]);
    const turn: ChatMessage[] = [{ id: "db-42", role: "user", content: "fix backend" }];
    const cards = sseEventToMessages(event(["python-backend"]), turn);
    expect(cards.slice(1)).toMatchObject([{
      id: "memory-references-42", role: "memory_references",
      // Bare keys from the SSE payload are normalised to reference objects.
      memory_references: [{ key: "python-backend" }],
    }]);
    expect(sseEventToMessages(event(["python-backend"]), cards)).toBe(cards);
  });

  it("inserts a late receipt after its user turn, not inside streaming thinking", () => {
    const event: SSEEvent = {
      type: "memory_references", timestamp: 0, data: { anchor_id: 42, keys: ["python-backend"] },
    };
    const streaming: ChatMessage[] = [
      { id: "db-42", role: "user", content: "fix backend" },
      { id: "t-1", role: "thinking", content: "The" },
    ];
    const result = sseEventToMessages(event, streaming);
    expect(result.map((m) => m.role)).toEqual(["user", "memory_references", "thinking"]);
    expect(result[2]).toBe(streaming[1]);
  });

  it("attaches a receipt to the optimistic user turn while streaming", () => {
    // During streaming the user turn has a local `u-<ts>` id, so the DB anchor
    // cannot be matched by id. The card must still appear instead of waiting
    // for the post-run reload.
    const event: SSEEvent = {
      type: "memory_references", timestamp: 0, data: { anchor_id: 42, keys: ["python-backend"] },
    };
    const streaming: ChatMessage[] = [
      { id: "u-1732000000000", role: "user", content: "fix backend" },
      { id: "s-1", role: "assistant", content: "thinking…", isStreaming: true },
    ];
    const result = sseEventToMessages(event, streaming);
    expect(result.map((m) => m.role)).toEqual(["user", "memory_references", "assistant"]);
    expect(result[1]).toMatchObject({
      id: "memory-references-42", memory_references: [{ key: "python-backend" }],
    });
  });

  it("drops a receipt whose user turn is no longer in view", () => {
    const event: SSEEvent = {
      type: "memory_references", timestamp: 0, data: { anchor_id: 99, keys: ["python-backend"] },
    };
    const messages: ChatMessage[] = [{ id: "db-42", role: "user", content: "fix backend" }];
    expect(sseEventToMessages(event, messages)).toBe(messages);
  });
});


it("restores a memory card immediately after its user turn", () => {
  const messages = dbMessagesToChat([
    { id: 42, sequence: 1, role: "user", content: "fix backend", created_at: null, memory_references: ["backend"] },
    { id: 43, sequence: 2, role: "assistant", content: "ok", created_at: null },
  ]);
  expect(messages.map((m) => m.role)).toEqual(["user", "memory_references", "assistant"]);
  expect(messages[1]).toMatchObject({
    id: "memory-references-42", memory_references: [{ key: "backend" }],
  });
});

import type { SSEEvent } from "../api/events";

const DELTA_TYPES = new Set(["text_delta", "thinking_delta", "bash_output"]);

// Coalesce consecutive text chunks, but never move them past a structural event.
export function createStreamEventBatcher(deliver: (event: SSEEvent) => void, delay = 50) {
  let pending: SSEEvent | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const flush = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
    const event = pending;
    pending = null;
    if (event) deliver(event);
  };

  return {
    push(event: SSEEvent) {
      if (!DELTA_TYPES.has(event.type)) {
        flush();
        deliver(event);
        return;
      }
      if (pending && (pending.type !== event.type || pending.data.role !== event.data.role ||
        pending.data.tool_call_id !== event.data.tool_call_id)) flush();
      pending = pending
        ? { ...pending, data: { ...pending.data, text: String(pending.data.text || "") + String(event.data.text || "") } }
        : { ...event, data: { ...event.data } };
      if (timer === null) timer = setTimeout(flush, delay);
    },
    clear() {
      if (timer !== null) clearTimeout(timer);
      timer = null;
      pending = null;
    },
  };
}

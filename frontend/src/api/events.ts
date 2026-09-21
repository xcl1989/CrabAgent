import { api } from "./client";

export interface SSEEvent {
  type: string;
  data: Record<string, unknown>;
  timestamp: number;
}

export function connectSSE(
  sessionId: string,
  onEvent: (event: SSEEvent) => void,
  onError?: (err: Event) => void,
): EventSource {
  const token = api.getToken();
  const url = `/api/events?session_id=${encodeURIComponent(sessionId)}&token=${encodeURIComponent(token || "")}`;
  const es = new EventSource(url);

  es.onmessage = (e) => {
    try {
      const event = JSON.parse(e.data) as SSEEvent;
      onEvent(event);
    } catch {
      // ignore non-JSON messages (keepalive etc)
    }
  };

  // The backend sends keepalives as a NAMED SSE event (`event: keepalive`),
  // which never fires `onmessage`. Without this listener the useSSE heartbeat
  // starved on idle sessions and forced a reconnect every 40s ("重新连接中").
  es.addEventListener("keepalive", () => {
    onEvent({ type: "keepalive", data: {}, timestamp: Date.now() });
  });

  es.onerror = () => {
    // EventSource auto-reconnects on error, just notify
    onError?.(new Event("error"));
  };

  return es;
}

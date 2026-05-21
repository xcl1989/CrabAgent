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

  es.onerror = (e) => {
    onError?.(e);
  };

  return es;
}

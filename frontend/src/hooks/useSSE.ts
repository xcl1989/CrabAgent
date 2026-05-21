import { useEffect, useRef, useCallback, useState } from "react";
import { connectSSE, SSEEvent } from "../api/events";

export function useSSE(sessionId: string | null, onEvent: (event: SSEEvent) => void) {
  const esRef = useRef<EventSource | null>(null);
  const [connected, setConnected] = useState(false);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const disconnect = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
      setConnected(false);
    }
  }, []);

  useEffect(() => {
    disconnect();
    if (!sessionId) return;

    const es = connectSSE(sessionId, (event) => {
      if (event.type === "connected") {
        setConnected(true);
      }
      onEventRef.current(event);
    });
    esRef.current = es;

    return disconnect;
  }, [sessionId, disconnect]);

  return { connected, disconnect };
}

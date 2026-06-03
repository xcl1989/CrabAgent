import { useEffect, useRef, useCallback, useState } from "react";
import { connectSSE, SSEEvent } from "../api/events";

const HEARTBEAT_TIMEOUT = 40000; // Reconnect if no event in 40s
const RECONNECT_DELAY = 2000;

export function useSSE(sessionId: string | null, onEvent: (event: SSEEvent) => void) {
  const esRef = useRef<EventSource | null>(null);
  const [connected, setConnected] = useState(false);
  const onEventRef = useRef(onEvent);
  const heartbeatRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  onEventRef.current = onEvent;

  const disconnect = useCallback(() => {
    if (reconnectRef.current) {
      clearTimeout(reconnectRef.current);
      reconnectRef.current = null;
    }
    if (heartbeatRef.current) {
      clearTimeout(heartbeatRef.current);
      heartbeatRef.current = null;
    }
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
      setConnected(false);
    }
  }, []);

  const connect = useCallback(() => {
    disconnect();
    if (!sessionId) return;

    const es = connectSSE(sessionId, (event: SSEEvent) => {
      // Reset heartbeat on every event (including keepalive)
      if (heartbeatRef.current) clearTimeout(heartbeatRef.current);
      heartbeatRef.current = setTimeout(() => {
        // No event received within timeout → reconnect
        disconnect();
        reconnectRef.current = setTimeout(connect, RECONNECT_DELAY);
      }, HEARTBEAT_TIMEOUT);

      if (event.type === "message_created" && event.data?.connected) {
        setConnected(true);
      } else if (event.type === "keepalive") {
        return; // Don't pass keepalive to handler
      }
      onEventRef.current(event);
    });

    esRef.current = es;
  }, [sessionId, disconnect]);

  useEffect(() => {
    connect();
    return disconnect;
  }, [connect, disconnect]);

  return { connected, disconnect };
}

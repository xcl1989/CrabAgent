import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { AttentionSummary } from "../api/work";
import { getAttentionSummary } from "../api/work";

/**
 * Global work-status provider (trusted work system §13).
 *
 * Single source of truth for persistent work state (waiting_user, failed,
 * partial, unread results). Loads via API, reconciles every 30s and on
 * window focus, so consumers (pet, switcher, bell, TaskPanel) stop
 * polling independently.
 */
interface WorkStatusValue {
  summary: AttentionSummary | null;
  loading: boolean;
  refresh: () => Promise<void>;
  unreadCount: number;
  waitingCount: number;
}

const WorkStatusContext = createContext<WorkStatusValue>({
  summary: null,
  loading: false,
  refresh: async () => {},
  unreadCount: 0,
  waitingCount: 0,
});

const RECONCILE_INTERVAL_MS = 30_000;

export function WorkStatusProvider({ children }: { children: React.ReactNode }) {
  const [summary, setSummary] = useState<AttentionSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const busy = useRef(false);

  const refresh = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    setLoading(true);
    try {
      setSummary(await getAttentionSummary());
    } catch {
      // keep last known state; SSE/next tick will reconcile
    } finally {
      busy.current = false;
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, RECONCILE_INTERVAL_MS);
    const onFocus = () => refresh();
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", onFocus);
    };
  }, [refresh]);

  const groups = summary?.groups ?? {};
  const waitingCount = (groups["pending_requests"] ?? []).length;
  const unreadCount =
    (groups["unread_results"] ?? []).length +
    (groups["failed_tasks"] ?? []).length +
    (groups["partial_tasks"] ?? []).length;

  return (
    <WorkStatusContext.Provider value={{ summary, loading, refresh, unreadCount, waitingCount }}>
      {children}
    </WorkStatusContext.Provider>
  );
}

export function useWorkStatus() {
  return useContext(WorkStatusContext);
}

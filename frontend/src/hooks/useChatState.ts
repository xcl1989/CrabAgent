import { useState, useRef, useEffect, useCallback } from "react";
import { ChatMessage } from "../types/ChatMessage";
import { SSEEvent } from "../api/events";
import { Session, Message } from "../api/sessions";
import * as sessionsApi from "../api/sessions";
import { sseEventToMessages, dbMessagesToChat } from "../lib/messageTransforms";
import { useSSE } from "./useSSE";

export function useChatState(onEvent?: (event: SSEEvent) => void, workspace?: string, onAutoLoadSession?: (session: Session) => void) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSession, setActiveSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [activeBranch, setActiveBranch] = useState<string>("main");
  const [replaying, setReplaying] = useState(false);
  const [replayProgress, setReplayProgress] = useState({ current: 0, total: 0 });
  const [todoRefreshKey, setTodoRefreshKey] = useState(0);
  const activeSessionRef = useRef<Session | null>(null);
  const pendingSubEventsRef = useRef<SSEEvent[]>([]);
  const subFlushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const subAgentContents = useRef<Map<string, string>>(new Map());

  const flushSubEvents = useCallback(() => {
    subFlushTimerRef.current = null;
    const events = pendingSubEventsRef.current;
    if (events.length === 0) return;
    pendingSubEventsRef.current = [];
    setMessages((prev) => {
      let msgs = prev;
      for (const ev of events) {
        const subId = (ev.data.sub_agent_id as string) || "";
        if (ev.type === "sub_agent_text_delta") {
          const text = (ev.data.text as string) || "";
          const prev_content = subAgentContents.current.get(subId) || "";
          subAgentContents.current.set(subId, prev_content + text);
        } else if (ev.type === "sub_agent_tool_call") {
          const name = (ev.data.name as string) || "";
          const args = JSON.stringify(ev.data.arguments || {});
          const prev_content = subAgentContents.current.get(subId) || "";
          subAgentContents.current.set(subId, prev_content + `\n→ ${name}(${args.slice(0, 120)})\n`);
        } else if (ev.type === "sub_agent_tool_result") {
          const name = (ev.data.name as string) || "";
          const result = (ev.data.result as string) || "";
          const prev_content = subAgentContents.current.get(subId) || "";
          subAgentContents.current.set(subId, prev_content + `\n← ${name}: ${result.slice(0, 200)}${result.length > 200 ? "..." : ""}\n`);
        } else if (ev.type === "sub_agent_end") {
          const resultText = (ev.data.result as string) || "";
          if (resultText) subAgentContents.current.set(subId, resultText);
          msgs = sseEventToMessages(ev, msgs);
        } else {
          msgs = sseEventToMessages(ev, msgs);
        }
      }
      return msgs;
    });
  }, []);

  const populateSubAgentContents = useCallback((chatMsgs: ChatMessage[]) => {
    for (const m of chatMsgs) {
      if (m.role === "sub_agent" && m.content && (m.sub_agent_id || m.id)) {
        const key = m.sub_agent_id || m.id;
        if (!subAgentContents.current.has(key)) {
          subAgentContents.current.set(key, m.content);
        }
      }
    }
  }, []);

  useEffect(() => {
    return () => {
      if (subFlushTimerRef.current) clearTimeout(subFlushTimerRef.current);
    };
  }, []);

  useEffect(() => {
    activeSessionRef.current = activeSession;
  }, [activeSession]);

  useEffect(() => {
    let cancelled = false;
    sessionsApi.listSessions(workspace).then((result) => {
      if (cancelled) return;
      setSessions(result);
      setSending(false);
      if (result.length > 0) {
        const latest = result[0];
        setActiveSession(latest);
        setActiveBranch(latest.active_branch || "main");
        if (latest.model) onAutoLoadSession?.(latest);
        sessionsApi.getMessages(latest.session_id).then((msgs) => {
          if (!cancelled) {
            const chatMsgs = dbMessagesToChat(msgs);
            populateSubAgentContents(chatMsgs);
            setMessages(chatMsgs);
          }
        });
      } else {
        setActiveSession(null);
        setMessages([]);
      }
    });
    return () => { cancelled = true; };
  }, [workspace, populateSubAgentContents, onAutoLoadSession]);

  const handleSSEEvent = useCallback(
    (event: SSEEvent) => {
      if (event.type === "tool_result") {
        const name = event.data.name as string;
        if (name === "todo_add" || name === "todo_done" || name === "todo_delete") {
          setTimeout(() => setTodoRefreshKey((k) => k + 1), 300);
        }
      }

      if (event.type === "agent_start" && event.data.replay) {
        setReplaying(true);
        setReplayProgress({ current: 0, total: (event.data.total as number) || 0 });
        setMessages([]);
        return;
      }
      if (event.type === "iteration_start" && event.data.replay_progress) {
        setReplayProgress({
          current: event.data.replay_progress as number,
          total: event.data.replay_total as number,
        });
        return;
      }
      if (event.type === "agent_end" && event.data.replay) {
        setReplaying(false);
        setReplayProgress({ current: 0, total: 0 });
        setTimeout(() => {
          sessionsApi.listSessions(workspace).then(setSessions);
        }, 500);
        return;
      }
      if (event.type === "text_delta" || event.type === "tool_call" || event.type === "thinking_delta" || event.type === "iteration_start" || event.type === "bash_output") {
        setSending(true);
      }
      if (event.type === "agent_end") {
        setSending(false);
        const stats = {
          elapsed: (event.data.elapsed_seconds as number) || 0,
          model: (event.data.model as string) || "",
          tokens: (event.data.tokens as number) || 0,
          iterations: (event.data.iterations as number) || 0,
        };
        setMessages((prev) => [...prev, { id: `stats-${Date.now()}`, role: "stats", content: "", stats }]);
        setTimeout(() => {
          sessionsApi.listSessions(workspace).then(setSessions);
        }, 500);
        const sid = activeSessionRef.current?.session_id;
        if (sid) {
          setTimeout(async () => {
            const msgs = await sessionsApi.getMessages(sid);
            const dbMsgs = dbMessagesToChat(msgs);
            populateSubAgentContents(dbMsgs);
            setMessages((prev) => {
              // Quick shape check: if DB messages have the same count, roles,
              // and content lengths as current, skip the replacement entirely
              // to avoid unnecessary DOM churn and scroll jumps.
              const sameShape =
                dbMsgs.length === prev.length &&
                dbMsgs.every(
                  (m, idx) =>
                    m.role === prev[idx]?.role &&
                    (m.content?.length || 0) === (prev[idx]?.content?.length || 0),
                );
              if (sameShape) return prev;

              const dbTotal = dbMsgs.reduce((s, m) => s + (m.content?.length || 0), 0);
              const prevTotal = prev.reduce((s, m) => s + (m.content?.length || 0), 0);
              // Preserve live-only SSE messages (screenshots, etc.) that
              // don't exist in DB. But skip if DB already has screenshots
              // (they carry inline base64, so no auth issues).
              const dbHasScreenshots = dbMsgs.some((m) => m.role === "screenshot");
              const liveOnly = dbHasScreenshots
                ? []
                : prev.filter((m) => m.role === "screenshot" && m.images?.length);
              if (dbTotal >= prevTotal) {
                return [...dbMsgs, ...liveOnly];
              }
              // Merge: keep prev + append any new DB messages
              const dbIds = new Set(dbMsgs.map((m) => m.id));
              const retained = prev.filter((m) => m.role === "screenshot" || !dbIds.has(m.id));
              return [...dbMsgs, ...retained.filter((m) => !dbMsgs.some((d) => d.id === m.id))];
            });
          }, 800);
        }
      }
      if (event.type.startsWith("sub_agent_")) {
        if (event.type === "sub_agent_start" || event.type === "sub_agent_end" || event.type === "sub_agent_error") {
          onEvent?.(event);
        }
        pendingSubEventsRef.current.push(event);
        if (!subFlushTimerRef.current) {
          subFlushTimerRef.current = setTimeout(flushSubEvents, 200);
        }
        return;
      }
      setMessages((prev) => sseEventToMessages(event, prev));
      onEvent?.(event);
    },
    [onEvent, workspace]
  );

  const { connected } = useSSE(activeSession?.session_id || null, handleSSEEvent);

  const selectSession = useCallback(
    async (session: Session, selectedModel: string, models: { id: string }[]) => {
      setActiveSession(session);
      const branch = session.active_branch || "main";
      setActiveBranch(branch);
      const msgs = await sessionsApi.getMessages(session.session_id);
      const chatMsgs = dbMessagesToChat(msgs);
      populateSubAgentContents(chatMsgs);
      setMessages(chatMsgs);

      // Check if this session has a running agent task — if so, restore "sending" state
      try {
        const { getAgentMonitor } = await import("../api/monitor");
        const monitors = await getAgentMonitor();
        const hasRunning = monitors.some(
          (m) => m.session_id === session.session_id && m.status === "running"
        );
        setSending(hasRunning);
      } catch {
        // If monitor check fails, assume not running
        setSending(false);
      }

      return session.model || (models.length > 0 ? models[0].id : selectedModel);
    },
    [populateSubAgentContents]
  );

  const newSession = useCallback(async (selectedModel: string, _models: { id: string }[]) => {
    setSending(false);
    const s = await sessionsApi.createSession(undefined, workspace);
    setSessions((prev) => [s, ...prev]);
    setActiveSession(s);
    setMessages([]);
    return selectedModel;
  }, [workspace]);

  // ── Background monitor: detect when non-active sessions finish ──
  // When a background agent completes, refresh session list so the UI stays in sync.
  const prevRunningRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const { getAgentMonitor } = await import("../api/monitor");
        const monitors = await getAgentMonitor();
        const nowRunning = new Set(monitors.filter((m) => m.status === "running").map((m) => m.session_id));
        const prevRunning = prevRunningRef.current;

        // Detect sessions that finished (were running, now not)
        const finished = [...prevRunning].filter((sid) => !nowRunning.has(sid));
        if (finished.length > 0) {
          // Refresh session list to update titles/timestamps
          sessionsApi.listSessions(workspace).then(setSessions);
        }

        // If the active session is among the finished ones, reload its messages
        const activeSid = activeSessionRef.current?.session_id;
        if (activeSid && finished.includes(activeSid)) {
          setSending(false);
          const msgs = await sessionsApi.getMessages(activeSid);
          const chatMsgs = dbMessagesToChat(msgs);
          populateSubAgentContents(chatMsgs);
          setMessages((prev) => {
            // Skip replacement if shape is identical to avoid unnecessary churn
            const sameShape =
              chatMsgs.length === prev.length &&
              chatMsgs.every(
                (m, idx) =>
                  m.role === prev[idx]?.role &&
                  (m.content?.length || 0) === (prev[idx]?.content?.length || 0),
              );
            if (sameShape) return prev;

            const dbTotal = chatMsgs.reduce((s, m) => s + (m.content?.length || 0), 0);
            const prevTotal = prev.reduce((s, m) => s + (m.content?.length || 0), 0);
            const dbHasScreenshots = chatMsgs.some((m) => m.role === "screenshot");
            const liveOnly = dbHasScreenshots
              ? []
              : prev.filter((m) => m.role === "screenshot" && m.images?.length);
            return dbTotal >= prevTotal ? [...chatMsgs, ...liveOnly] : prev;
          });
        }

        prevRunningRef.current = nowRunning;
      } catch {
        // Silently ignore monitor errors
      }
    }, 5000); // Check every 5 seconds

    return () => clearInterval(interval);
  }, [workspace, populateSubAgentContents]);

  const selectSessionById = useCallback(
    async (sessionId: string, selectedModel: string, models: { id: string }[]) => {
      try {
        const s = await sessionsApi.getSession(sessionId);
        if (s) {
          setSessions((prev) => {
            if (prev.some((x) => x.session_id === s.session_id)) return prev;
            return [s, ...prev];
          });
          return selectSession(s, selectedModel, models);
        }
      } catch {
        /* ignore */
      }
      return selectedModel;
    },
    [selectSession]
  );

  const startReplay = useCallback(
    (branchId: string) => {
      if (!activeSession || replaying) return;
      const sid = activeSession.session_id;
      const token = localStorage.getItem("crab_token") || "";
      const url = `/api/sessions/${encodeURIComponent(sid)}/replay?branch=${encodeURIComponent(branchId)}&token=${encodeURIComponent(token)}&speed=1`;
      const es = new EventSource(url);
      es.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data) as SSEEvent;
          handleSSEEvent(event);
        } catch {
          /* ignore */
        }
      };
      es.onerror = () => {
        setReplaying(false);
        es.close();
      };
      setReplaying(true);
    },
    [activeSession, replaying, handleSSEEvent]
  );

  const handleSwitchBranch = useCallback(
    async (branchId: string) => {
      if (!activeSession) return;
      await sessionsApi.switchBranch(activeSession.session_id, branchId);
      setActiveBranch(branchId);
      setActiveSession({ ...activeSession, active_branch: branchId });
      const msgs = await sessionsApi.getMessages(activeSession.session_id);
      const chatMsgs = dbMessagesToChat(msgs);
      populateSubAgentContents(chatMsgs);
      setMessages(chatMsgs);
    },
    [activeSession, populateSubAgentContents]
  );

  const handleBranch = useCallback(
    async (msgId: string) => {
      if (!activeSession) return;
      const dbId = parseInt(msgId.replace("db-", ""), 10);
      if (isNaN(dbId)) return;
      const result = await sessionsApi.createBranch(activeSession.session_id, dbId);
      setActiveBranch(result.branch_id);
      setActiveSession({ ...activeSession, active_branch: result.branch_id });
      const msgs = await sessionsApi.getMessages(activeSession.session_id);
      setMessages(dbMessagesToChat(msgs));
    },
    [activeSession]
  );

  const handleAbort = useCallback(async () => {
    if (activeSession) {
      await sessionsApi.abortSession(activeSession.session_id);
      setSending(false);
    }
  }, [activeSession]);

  const handleDeleteSession = useCallback(
    async (sessionId: string) => {
      await sessionsApi.deleteSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
      if (activeSession?.session_id === sessionId) {
        setActiveSession(null);
        setMessages([]);
      }
    },
    [activeSession]
  );

  const getSubAgentContent = useCallback((subId: string) => {
    return subAgentContents.current.get(subId) || "";
  }, []);

  return {
    sessions,
    setSessions,
    activeSession,
    setActiveSession,
    messages,
    setMessages,
    sending,
    setSending,
    connected,
    activeBranch,
    replaying,
    replayProgress,
    todoRefreshKey,
    selectSession,
    newSession,
    selectSessionById,
    startReplay,
    handleSSEEvent,
    handleSwitchBranch,
    handleBranch,
    handleAbort,
    handleDeleteSession,
    getSubAgentContent,
  };
}

import { useState, useRef, useEffect, useCallback } from "react";
import { useSSE } from "../hooks/useSSE";
import { SSEEvent } from "../api/events";
import * as sessionsApi from "../api/sessions";
import { Session, Message } from "../api/sessions";
import * as providersApi from "../api/providers";
import { Provider, CatalogEntry, ModelInfo } from "../api/providers";
import * as mcpServersApi from "../api/mcpServers";
import { McpServer, McpServerStatus } from "../api/mcpServers";
import SessionList from "../components/SessionList";
import ChatPanel from "../components/ChatPanel";
import ProviderPanel from "../components/ProviderPanel";
import McpServerPanel from "../components/McpServerPanel";
import McpStatusBar from "../components/McpStatusBar";
import BranchSelector from "../components/BranchSelector";
import FileBrowser from "../components/FileBrowser";
import TodoWidget from "../components/TodoWidget";

interface ChatMessage {
  id: string;
  role: string;
  content: string;
  reasoning_content?: string;
  tool_calls?: unknown[];
  isStreaming?: boolean;
  stats?: { elapsed: number; model: string; tokens: number; iterations: number };
  confirm_id?: string;
  tool_name?: string;
  args_summary?: string;
  confirmed?: boolean;
  options?: string[];
  source?: "builtin" | "mcp";
  server_name?: string;
}

function sseEventToMessages(event: SSEEvent, messages: ChatMessage[]): ChatMessage[] {
  const updated = [...messages];

  if (event.type === "text_delta") {
    const last = updated[updated.length - 1];
    if (last?.role === "assistant" && last.isStreaming) {
      last.content += event.data.text as string || "";
      return updated;
    }
    updated.push({ id: `s-${Date.now()}`, role: (event.data.role as string) || "assistant", content: event.data.text as string || "", isStreaming: true });
    return updated;
  }

  if (event.type === "thinking_delta") {
    const last = updated[updated.length - 1];
    if (last?.role === "thinking") {
      last.content += event.data.text as string || "";
      return updated;
    }
    updated.push({ id: `t-${Date.now()}`, role: "thinking", content: event.data.text as string || "" });
    return updated;
  }

  if (event.type === "text_done") {
    return updated.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m));
  }

  if (event.type === "tool_call") {
    const callId = event.data.id as string;
    if (callId && messages.some(m => m.id === `tc-${callId}`)) {
      return messages;
    }
    updated.push({
      id: callId ? `tc-${callId}` : `tc-${Date.now()}`,
      role: "tool_call",
      content: JSON.stringify({ name: event.data.name, arguments: event.data.arguments }),
      source: (event.data.source as "builtin" | "mcp") || "builtin",
      server_name: (event.data.server_name as string) || undefined,
    });
    return updated;
  }

  if (event.type === "tool_result") {
    const callId = event.data.id as string;
    if (callId && messages.some(m => m.id === `tr-${callId}`)) {
      return messages;
    }
    updated.push({
      id: callId ? `tr-${callId}` : `tr-${Date.now()}`,
      role: "tool_result",
      content: (event.data.result as string) || "",
      source: (event.data.source as "builtin" | "mcp") || "builtin",
      server_name: (event.data.server_name as string) || undefined,
    });
    return updated;
  }

  if (event.type === "agent_error") {
    updated.push({ id: `e-${Date.now()}`, role: "error", content: (event.data.error as string) || "Unknown error" });
    return updated;
  }

  if (event.type === "tool_confirm_request") {
    updated.push({
      id: `cf-${event.data.confirm_id}`,
      role: "tool_confirm",
      content: "",
      confirm_id: event.data.confirm_id as string,
      tool_name: event.data.tool_name as string,
      args_summary: event.data.args_summary as string,
    });
    return updated;
  }

  if (event.type === "user_input_request") {
    const opts = event.data.options as string[] | undefined;
    console.log("USER_INPUT_REQUEST", event.data.input_id, event.data.question, opts);
    updated.push({
      id: `in-${event.data.input_id}`,
      role: "user_input",
      content: event.data.question as string || "",
      confirm_id: event.data.input_id as string,
      options: opts && opts.length > 0 ? opts : undefined,
    });
    return updated;
  }

  if (event.type === "context_compressed") {
    const orig = event.data.original_count as number;
    const comp = event.data.compressed_count as number;
    updated.push({
      id: `cc-${Date.now()}`,
      role: "notice",
      content: `Context compressed: ${orig} → ${comp} messages`,
    });
    return updated;
  }

  return updated;
}

function dbMessagesToChat(msgs: Message[]): ChatMessage[] {
  const result: ChatMessage[] = [];
  const pendingToolCalls: { id: string; name: string; args: any }[] = [];

  for (const m of msgs) {
    if (m.role === "stats" && m.content) {
      try {
        const raw = JSON.parse(m.content);
        result.push({
          id: `db-${m.id}`,
          role: "stats",
          content: "",
          stats: {
            elapsed: raw.elapsed_seconds ?? raw.elapsed ?? 0,
            model: raw.model ?? "",
            tokens: raw.tokens ?? 0,
            iterations: raw.iterations ?? 0,
          },
        });
      } catch { /* ignore */ }
      continue;
    }

    if (m.role === "tool") {
      const tcId = m.tool_call_id as string | undefined;
      const matched = tcId ? pendingToolCalls.findIndex(tc => tc.id === tcId) : -1;
      if (matched >= 0) {
        const tc = pendingToolCalls.splice(matched, 1)[0];
        result.push({
          id: `db-${m.id}-tc`,
          role: "tool_call",
          content: JSON.stringify({ name: tc.name, arguments: tc.args }),
        });
      }
      result.push({
        id: `db-${m.id}`,
        role: "tool_result",
        content: m.content || "",
      });
      continue;
    }

    if (m.role === "assistant" && m.tool_calls) {
      const tc = typeof m.tool_calls === "string" ? JSON.parse(m.tool_calls) : m.tool_calls;
      if (m.content || m.reasoning_content) {
        const base: ChatMessage = { id: `db-${m.id}-text`, role: "assistant", content: m.content || "" };
        if (m.reasoning_content) base.reasoning_content = m.reasoning_content;
        result.push(base);
      }
      for (const tcItem of tc as any[]) {
        const fn = tcItem.function || {};
        let args = fn.arguments;
        if (typeof args === "string") { try { args = JSON.parse(args); } catch { /* keep string */ } }
        pendingToolCalls.push({ id: tcItem.id, name: fn.name || "", args: args || {} });
      }
      continue;
    }

    const base: ChatMessage = { id: `db-${m.id}`, role: m.role, content: m.content || "" };
    if (m.reasoning_content) base.reasoning_content = m.reasoning_content;
    result.push(base);
  }

  return result;
}

interface Props {
  onLogout: () => void;
}

export default function ChatPage({ onLogout }: Props) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSession, setActiveSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [showProviders, setShowProviders] = useState(false);
  const [showMcpServers, setShowMcpServers] = useState(false);
  const [mcpServers, setMcpServers] = useState<McpServer[]>([]);
  const [mcpStatus, setMcpStatus] = useState<McpServerStatus[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [providersLoading, setProvidersLoading] = useState(true);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [activeBranch, setActiveBranch] = useState<string>("main");
  const [replaying, setReplaying] = useState(false);
  const [replayProgress, setReplayProgress] = useState({ current: 0, total: 0 });
  const [showFiles, setShowFiles] = useState(false);
  const [todoRefreshKey, setTodoRefreshKey] = useState(0);
  const activeSessionRef = useRef<Session | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const prevMsgCountRef = useRef(0);

  useEffect(() => {
    activeSessionRef.current = activeSession;
  }, [activeSession]);

  useEffect(() => {
    sessionsApi.listSessions().then(setSessions);
  }, []);

  const handleSSEEvent = useCallback((event: SSEEvent) => {
    if (event.type === "tool_result") {
      const name = event.data.name as string;
      if (name === "todo_add" || name === "todo_done" || name === "todo_delete") {
        setTimeout(() => setTodoRefreshKey(k => k + 1), 300);
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
        sessionsApi.listSessions().then(setSessions);
      }, 500);
      return;
    }
    if (event.type === "text_delta" || event.type === "tool_call" || event.type === "thinking_delta" || event.type === "iteration_start") {
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
      setMessages((prev) => [
        ...prev,
        { id: `stats-${Date.now()}`, role: "stats", content: "", stats },
      ]);
      setTimeout(() => {
        sessionsApi.listSessions().then(setSessions);
      }, 500);
      const sid = activeSessionRef.current?.session_id;
      if (sid) {
        setTimeout(async () => {
          const msgs = await sessionsApi.getMessages(sid);
          const dbMsgs = dbMessagesToChat(msgs);
          setMessages((prev) => (dbMsgs.length > prev.length ? dbMsgs : prev));
        }, 800);
      }
    }
    setMessages((prev) => sseEventToMessages(event, prev));
  }, []);

  const { connected } = useSSE(activeSession?.session_id || null, handleSSEEvent);

  useEffect(() => {
    if (messages.length > prevMsgCountRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
    prevMsgCountRef.current = messages.length;
  }, [messages]);

  useEffect(() => {
    providersApi.listProviders().then((p) => {
      setProviders(p);
      setProvidersLoading(false);
    });
    providersApi.getCatalog().then(setCatalog);
    mcpServersApi.listMcpServers().then(setMcpServers);
    mcpServersApi.getMcpStatus().then(setMcpStatus);
  }, []);

  useEffect(() => {
    const interval = setInterval(() => {
      mcpServersApi.getMcpStatus().then(setMcpStatus).catch(() => {});
    }, 60000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const defaultProvider = providers.find((p) => p.is_default);
    if (defaultProvider) {
      providersApi.getProviderModels(defaultProvider.name).then((m) => {
        setModels(m);
        if (m.length > 0 && !selectedModel) {
          setSelectedModel(m[0].id);
        }
      }).catch(() => {});
    }
  }, [providers]);

  const selectSession = async (session: Session) => {
    setActiveSession(session);
    const branch = session.active_branch || "main";
    setActiveBranch(branch);
    const msgs = await sessionsApi.getMessages(session.session_id);
    setMessages(dbMessagesToChat(msgs));
    setSelectedModel(session.model || (models.length > 0 ? models[0].id : ""));
  };

  const newSession = async () => {
    const s = await sessionsApi.createSession();
    setSessions((prev) => [s, ...prev]);
    setActiveSession(s);
    setMessages([]);
    setSelectedModel(models.length > 0 ? models[0].id : "");
  };

  const handleSend = async () => {
    if (!input.trim() || !activeSession || sending) return;
    const text = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { id: `u-${Date.now()}`, role: "user", content: text }]);
    setSending(true);
    try {
      await sessionsApi.sendPrompt(activeSession.session_id, text, selectedModel);
    } catch {
      setSending(false);
    }
  };

  const handleToolConfirm = async (confirmId: string, approved: boolean) => {
    if (!activeSession) return;
    setMessages((prev) =>
      prev.map((m) =>
        m.confirm_id === confirmId ? { ...m, confirmed: approved } : m
      )
    );
    try {
      await sessionsApi.confirmTool(activeSession.session_id, confirmId, approved);
    } catch {
      // ignore
    }
  };

  const handleUserInput = async (inputId: string, answer: string) => {
    if (!activeSession) return;
    setMessages((prev) =>
      prev.map((m) =>
        m.confirm_id === inputId ? { ...m, confirmed: true, content: answer } : m
      )
    );
    try {
      await sessionsApi.submitInput(activeSession.session_id, inputId, answer);
    } catch {
      // ignore
    }
  };

  const handleSwitchBranch = async (branchId: string) => {
    if (!activeSession) return;
    await sessionsApi.switchBranch(activeSession.session_id, branchId);
    setActiveBranch(branchId);
    setActiveSession({ ...activeSession, active_branch: branchId });
    const msgs = await sessionsApi.getMessages(activeSession.session_id);
    setMessages(dbMessagesToChat(msgs));
  };

  const handleBranch = async (msgId: string) => {
    if (!activeSession) return;
    const dbId = parseInt(msgId.replace("db-", ""), 10);
    if (isNaN(dbId)) return;
    const result = await sessionsApi.createBranch(activeSession.session_id, dbId);
    setActiveBranch(result.branch_id);
    setActiveSession({ ...activeSession, active_branch: result.branch_id });
    const msgs = await sessionsApi.getMessages(activeSession.session_id);
    setMessages(dbMessagesToChat(msgs));
  };

  const startReplay = (branchId: string) => {
    if (!activeSession || replaying) return;
    const sid = activeSession.session_id;
    const token = localStorage.getItem("crab_token") || "";
    const url = `/api/sessions/${encodeURIComponent(sid)}/replay?branch=${encodeURIComponent(branchId)}&token=${encodeURIComponent(token)}&speed=1`;
    const es = new EventSource(url);
    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data) as SSEEvent;
        handleSSEEvent(event);
      } catch { /* ignore */ }
    };
    es.onerror = () => {
      setReplaying(false);
      es.close();
    };
    setReplaying(true);
  };

  const handleAbort = async () => {
    if (activeSession) {
      await sessionsApi.abortSession(activeSession.session_id);
      setSending(false);
    }
  };

  const handleDeleteSession = async (sessionId: string) => {
    await sessionsApi.deleteSession(sessionId);
    setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
    if (activeSession?.session_id === sessionId) {
      setActiveSession(null);
      setMessages([]);
    }
  };

  return (
    <div className="flex h-screen">
      <SessionList
        sessions={sessions}
        activeId={activeSession?.session_id || null}
        onSelect={selectSession}
        onNew={newSession}
        onDelete={handleDeleteSession}
        onLogout={onLogout}
        onOpenProviders={() => setShowProviders(true)}
        onOpenMcpServers={() => setShowMcpServers(true)}
      />

      <div className="flex-1 flex flex-col min-w-0">
        {activeSession ? (
          <>
            <div className="flex items-center border-b" style={{ borderBottom: "1px solid var(--border)" }}>
              <div className="flex-1">
                <BranchSelector
                  sessionId={activeSession.session_id}
                  activeBranch={activeBranch}
                  onSwitch={handleSwitchBranch}
                  onReplay={startReplay}
                />
              </div>
              <button
                onClick={() => setShowFiles((v) => !v)}
                className="px-3 py-2 text-sm"
                style={{ color: showFiles ? "var(--accent)" : "var(--text-secondary)" }}
                title="Toggle file browser"
              >
                📁
              </button>
            </div>
            {replaying && replayProgress.total > 0 && (
              <div className="px-4 pt-2 pb-1" style={{ borderBottom: "1px solid var(--border)" }}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs" style={{ color: "#34d399" }}>▶ Replaying branch</span>
                  <span className="text-xs" style={{ color: "var(--text-secondary)", fontFamily: "'SF Mono', monospace" }}>
                    {replayProgress.current} / {replayProgress.total}
                  </span>
                </div>
                <div className="h-1 rounded-full overflow-hidden" style={{ background: "var(--bg-tertiary)" }}>
                  <div
                    className="h-full transition-all duration-200 rounded-full"
                    style={{
                      width: `${(replayProgress.current / replayProgress.total) * 100}%`,
                      background: "linear-gradient(90deg, #34d399, #67e8f9)",
                    }}
                  />
                </div>
              </div>
            )}
            <ChatPanel ref={bottomRef} messages={messages} connected={connected} onToolConfirm={handleToolConfirm} onUserInput={handleUserInput} onBranch={handleBranch} replaying={replaying} />

            <McpStatusBar status={mcpStatus} />

            <div className="px-4 pb-4">
              {models.length > 0 && (
                <div className="mb-2 flex items-center gap-2">
                  <span className="text-xs" style={{ color: "var(--text-secondary)" }}>Model:</span>
                  <select
                    value={selectedModel}
                    onChange={(e) => setSelectedModel(e.target.value)}
                    className="text-xs px-2 py-1 rounded outline-none"
                    style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                  >
                    {models.map((m) => (
                      <option key={m.id} value={m.id}>{m.id}</option>
                    ))}
                  </select>
                </div>
              )}
              <div className="flex gap-2">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
                  placeholder="Type a message..."
                  disabled={sending || replaying}
                  className="flex-1 px-4 py-3 rounded-lg text-sm outline-none disabled:opacity-50"
                  style={{ background: "var(--bg-secondary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                />
                {sending ? (
                  <button
                    onClick={handleAbort}
                    className="px-4 py-3 rounded-lg text-sm font-medium"
                    style={{ background: "var(--danger)", color: "#fff" }}
                  >
                    Stop
                  </button>
                ) : (
                  <button
                    onClick={handleSend}
                    disabled={!input.trim()}
                    className="px-4 py-3 rounded-lg text-sm font-medium text-white disabled:opacity-50"
                    style={{ background: "var(--accent)" }}
                  >
                    Send
                  </button>
                )}
              </div>
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center" style={{ color: "var(--text-secondary)" }}>
            <div className="text-center">
              <p className="text-lg mb-2">CrabAgent</p>
              <p className="text-sm">Select a session or create a new one</p>
            </div>
          </div>
        )}
      </div>

      <FileBrowser collapsed={!showFiles} onToggle={() => setShowFiles((v) => !v)} sessionId={activeSession?.session_id || null} />

      <TodoWidget sessionId={activeSession?.session_id || null} refreshKey={todoRefreshKey} />

      {showProviders && (
        <ProviderPanel
          providers={providers}
          catalog={catalog}
          onClose={() => setShowProviders(false)}
          onRefresh={() => {
            providersApi.listProviders().then(setProviders);
          }}
        />
      )}

      {!providersLoading && providers.length === 0 && (
        <div className="fixed inset-0 z-40 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.7)" }}>
          <div
            className="w-full max-w-sm rounded-xl p-8 text-center"
            style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}
          >
            <div className="text-3xl mb-4">&#x26a0;&#xfe0f;</div>
            <h2 className="text-lg font-semibold mb-2">No Provider Configured</h2>
            <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>
              CrabAgent needs at least one LLM provider to function. Please add a provider to get started.
            </p>
            <button
              onClick={() => setShowProviders(true)}
              className="w-full py-3 rounded-lg text-sm font-medium text-white"
              style={{ background: "var(--accent)" }}
            >
              + Add Provider
            </button>
          </div>
        </div>
      )}

      {showMcpServers && (
        <McpServerPanel
          servers={mcpServers}
          status={mcpStatus}
          onClose={() => setShowMcpServers(false)}
          onRefresh={() => {
            mcpServersApi.listMcpServers().then(setMcpServers);
            mcpServersApi.getMcpStatus().then(setMcpStatus);
          }}
        />
      )}
    </div>
  );
}

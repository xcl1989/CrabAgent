import { useCallback, useEffect, useRef, useState } from "react";
import * as sessionsApi from "../api/sessions";
import { useSSE } from "../hooks/useSSE";
import { sseEventToMessages } from "../lib/messageTransforms";
import { ChatMessage } from "../types/ChatMessage";
import { SSEEvent } from "../api/events";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Globe2,
  Loader2,
  RefreshCw,
  SendHorizontal,
  ShieldCheck,
  Square,
  X,
  ChevronDown,
  ChevronRight,
  FolderOpen,
  History,
  LayoutList,
  Plus,
} from "lucide-react";
import WorkspaceSwitcher from "../components/WorkspaceSwitcher";

type BrowserAction = "back" | "forward" | "reload" | "stop";
type SessionScope = "browser" | "workspace" | "all";

interface BrowserState {
  url: string;
  title: string;
  canGoBack: boolean;
  canGoForward: boolean;
  loading: boolean;
}

const START_URL = "https://www.google.com/";
const ACTIVITY_PREVIEW_LIMIT = 8;

function formatUrl(url: string): string {
  if (!url) return START_URL;
  return /^[a-z][a-z\d+.-]*:/i.test(url) ? url : `https://${url}`;
}

interface Props {
  initialSessionId: string | null;
  onSessionChange: (sessionId: string | null) => void;
}

function workspaceName(workspace: string): string {
  return workspace.split("/").pop() || workspace || "默认工作空间";
}

export default function BrowserCollaborationPage({ initialSessionId, onSessionChange }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const addressEditingRef = useRef(false);
  const pendingNavigationRef = useRef<string | null>(null);
  const [task, setTask] = useState("");
  const [browserState, setBrowserState] = useState<BrowserState>({
    url: START_URL,
    title: "协作浏览器",
    canGoBack: false,
    canGoForward: false,
    loading: false,
  });
  const [address, setAddress] = useState(START_URL);
  const [available, setAvailable] = useState(Boolean(window.electronAPI?.collaborationBrowserLayout));
  const [error, setError] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [session, setSession] = useState<sessionsApi.Session | null>(null);
  const [sessions, setSessions] = useState<sessionsApi.Session[]>([]);
  const [newWorkspace, setNewWorkspace] = useState("");
  const [workspaceFilter, setWorkspaceFilter] = useState("");
  const [sessionScope, setSessionScope] = useState<SessionScope>("browser");
  const [sessionMenuOpen, setSessionMenuOpen] = useState(false);
  const [sessionQuery, setSessionQuery] = useState("");
  const [sessionLoading, setSessionLoading] = useState(false);
  const [creatingSession, setCreatingSession] = useState(false);
  const [contextPanelCollapsed, setContextPanelCollapsed] = useState(false);
  const [browserTasks, setBrowserTasks] = useState<sessionsApi.BrowserTask[]>([]);
  const [activeBrowserTask, setActiveBrowserTask] = useState<sessionsApi.BrowserTask | null>(null);
  const [taskEvents, setTaskEvents] = useState<sessionsApi.BrowserTaskEvent[]>([]);
  const activeBrowserTaskRef = useRef<sessionsApi.BrowserTask | null>(null);
  const sessionIdRef = useRef("");
  const sessionLoadRef = useRef(0);
  const initialLoadDoneRef = useRef(false);
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activityLoaded, setActivityLoaded] = useState(false);
  const [pendingConfirm, setPendingConfirm] = useState<ChatMessage | null>(null);
  const [pendingInput, setPendingInput] = useState<ChatMessage | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const actionRequiredRef = useRef<HTMLDivElement>(null);
  const connectedRef = useRef(false);

  const lastBoundsRef = useRef("");
  const syncTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const syncBounds = useCallback(() => {
    if (syncTimerRef.current) clearTimeout(syncTimerRef.current);
    syncTimerRef.current = setTimeout(() => {
      const host = hostRef.current;
      const bridge = window.electronAPI?.collaborationBrowserLayout;
      if (!host || !bridge) return;
      const rect = host.getBoundingClientRect();
      const w = Math.round(rect.width);
      const h = Math.round(rect.height);
      if (w < 10 || h < 10) return;
      const key = `${Math.round(rect.left)},${Math.round(rect.top)},${w},${h}`;
      if (key === lastBoundsRef.current) return;
      lastBoundsRef.current = key;
      void bridge({ x: rect.left, y: rect.top, width: rect.width, height: rect.height }, true)
        .catch(() => {});
    }, 200);
  }, []);

  useEffect(() => {
    const bridge = window.electronAPI?.collaborationBrowserLayout;
    setAvailable(Boolean(bridge));
    if (!bridge) return;

    const observer = new ResizeObserver(syncBounds);
    if (hostRef.current) observer.observe(hostRef.current);
    syncBounds();
    return () => {
      observer.disconnect();
      void bridge(null, false);
    };
  }, [syncBounds]);

  useEffect(() => {
    window.electronAPI?.onCollaborationBrowserState?.((next) => {
      setBrowserState(next);
      const pending = pendingNavigationRef.current;
      // Electron emits a loading event for the old page before loadURL updates its URL.
      // Keep the user's target visible until the native view reaches it.
      if (!addressEditingRef.current && (!pending || next.url === pending)) {
        setAddress(next.url || "");
        if (pending && next.url === pending) pendingNavigationRef.current = null;
      }
      setError("");
    });
  }, []);

  const navigate = useCallback(async () => {
    const bridge = window.electronAPI?.collaborationBrowserNavigate;
    if (!bridge) {
      setError("错误：浏览器桥接不可用（collaborationBrowserNavigate 未定义）");
      return;
    }
    const target = formatUrl(address);
    pendingNavigationRef.current = target;
    addressEditingRef.current = false;
    setAddress(target);
    try {
      setError("");
      const result = await bridge(target);
      setError(`导航已发送：${target}`);
    } catch (reason) {
      setError(`导航失败：${reason instanceof Error ? reason.message : String(reason)}`);
    }
  }, [address]);

  const handleSSEEvent = useCallback((event: SSEEvent) => {
    const taskRecord = activeBrowserTaskRef.current;
    const currentSessionId = sessionIdRef.current;
    if (taskRecord && currentSessionId && (event.type === "tool_call" || event.type === "tool_result" || event.type === "agent_end" || event.type === "agent_error")) {
      const name = String(event.data.name || "");
      const result = String(event.data.result || "");
      const isBrowserAction = name.startsWith("collab_browser_");
      if (isBrowserAction || event.type === "agent_end" || event.type === "agent_error") {
        const risk = result.includes("confirmation_required") || /payment|delete|send|支付|删除|发送/i.test(name) ? "high" : "low";
        void sessionsApi.createBrowserTaskEvent(currentSessionId, taskRecord.id, {
          event_type: event.type,
          detail: name || (event.type === "agent_error" ? String(event.data.error || "Agent failed") : "Agent completed"),
          risk,
          data: isBrowserAction ? { tool: name } : {},
        });
      }
      if (event.type === "agent_end" || event.type === "agent_error") {
        const nextStatus = event.type === "agent_end" ? "completed" : "failed";
        void sessionsApi.updateBrowserTask(currentSessionId, taskRecord.id, { status: nextStatus, url: browserState.url })
          .then((updated) => {
            setActiveBrowserTask(updated);
            setBrowserTasks((items) => items.map((item) => item.id === updated.id ? updated : item));
          })
          .catch(() => {});
      }
    }
    if (event.type === "tool_confirm_request") {
      setPendingConfirm({
        id: `cf-${Date.now()}`,
        role: "tool_confirm",
        content: "",
        confirm_id: event.data.confirm_id as string,
        tool_name: event.data.tool_name as string,
        args_summary: event.data.args_summary as string,
      });
    } else if (event.type === "user_input_request") {
      setPendingInput({
        id: `in-${Date.now()}`,
        role: "user_input",
        content: (event.data.question as string) || "",
        confirm_id: event.data.input_id as string,
        options: (event.data.options as string[] | undefined) || undefined,
      });
    } else if (event.type === "agent_end") {
      setSending(false);
    } else if (event.type === "agent_error") {
      setSending(false);
      setMessages((prev) => [
        ...prev,
        { id: `e-${Date.now()}`, role: "error", content: (event.data.error as string) || "Unknown error" },
      ]);
    } else {
      setMessages((prev) => sseEventToMessages(event, prev));
    }
  }, [browserState.url]);

  const { connected } = useSSE(sessionId || null, handleSSEEvent);

  const loadSession = useCallback(async (nextSessionId: string) => {
    const loadId = ++sessionLoadRef.current;
    // Update synchronously so stale SSE callbacks cannot append to the next view.
    sessionIdRef.current = nextSessionId;
    setSessionId(nextSessionId);
    setSessionLoading(true);
    // Switch the task context first. Recent chat activity is loaded separately
    // so a long conversation never blocks collaboration browser controls.
    setMessages([]);
    setActivityLoaded(false);
    setPendingConfirm(null);
    setPendingInput(null);
    try {
      const [nextSession, taskResult] = await Promise.all([
        sessionsApi.getSession(nextSessionId),
        sessionsApi.listBrowserTasks(nextSessionId),
      ]);
      if (loadId !== sessionLoadRef.current) return;
      setSession(nextSession);
      setNewWorkspace(nextSession.workspace || "");
      setBrowserTasks(taskResult.tasks);
      setActiveBrowserTask(taskResult.tasks.find((item) => ["running", "waiting_for_user", "paused"].includes(item.status)) || taskResult.tasks[0] || null);
      onSessionChange(nextSession.session_id);
      void sessionsApi.getMessages(nextSessionId, ACTIVITY_PREVIEW_LIMIT, false)
        .then((storedMessages) => {
          if (loadId !== sessionLoadRef.current) return;
          setMessages(storedMessages.map((message) => ({
            id: `preview-${message.id}`,
            role: message.role,
            content: message.content,
            tool_name: message.name,
          })));
        })
        .catch(() => {
          if (loadId === sessionLoadRef.current) setMessages([]);
        })
        .finally(() => {
          if (loadId === sessionLoadRef.current) setActivityLoaded(true);
        });
    } finally {
      setSessionLoading(false);
    }
  }, [onSessionChange]);

  const refreshSessions = useCallback(async (workspace = workspaceFilter, scope = sessionScope) => {
    const result = await sessionsApi.listSessions(
      scope === "all" ? undefined : workspace || undefined,
      scope === "browser",
    );
    setSessions(result);
  }, [sessionScope, workspaceFilter]);

  useEffect(() => {
    void refreshSessions().catch(() => {});
  }, [refreshSessions]);

  useEffect(() => {
    if (!initialSessionId || sessionScope !== "browser") return;
    if (sessions.some((item) => item.session_id === initialSessionId)) return;
    // Keep the active chat context available even before it has a browser task.
    sessionsApi.getSession(initialSessionId).then((current) => {
      setSessions((items) => items.some((item) => item.session_id === current.session_id) ? items : [current, ...items]);
    }).catch(() => {});
  }, [initialSessionId, sessionScope, sessions]);

  useEffect(() => {
    // Only use initialSessionId for the very first load. After that, the
    // browser page owns its own session selection — the chat page must not
    // be able to yank it away by changing its own active session.
    if (initialLoadDoneRef.current) return;
    if (!initialSessionId) return;
    initialLoadDoneRef.current = true;
    void loadSession(initialSessionId).catch((reason) => {
      setError(reason instanceof Error ? reason.message : "无法加载当前对话");
    });
  }, [initialSessionId, loadSession]);

  useEffect(() => {
    if (sessionId || initialLoadDoneRef.current) return;
    const savedSessionId = window.localStorage.getItem("crabagent_collaboration_session_id");
    if (savedSessionId) {
      initialLoadDoneRef.current = true;
      void loadSession(savedSessionId).catch(() => window.localStorage.removeItem("crabagent_collaboration_session_id"));
    }
  }, [loadSession, sessionId]);

  useEffect(() => {
    if (sessionId) window.localStorage.setItem("crabagent_collaboration_session_id", sessionId);
  }, [sessionId]);

  useEffect(() => {
    connectedRef.current = connected;
  }, [connected]);

  useEffect(() => {
    activeBrowserTaskRef.current = activeBrowserTask;
    if (!activeBrowserTask || !sessionId) {
      setTaskEvents([]);
      return;
    }
    sessionsApi.listBrowserTaskEvents(sessionId, activeBrowserTask.id)
      .then((result) => setTaskEvents(result.events))
      .catch(() => setTaskEvents([]));
  }, [activeBrowserTask, sessionId]);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: sending ? "smooth" : "auto", block: "nearest" });
  }, [messages, sending]);

  useEffect(() => {
    if (!pendingConfirm && !pendingInput) return;
    // Approval and human handoff must take precedence over passive activity updates.
    requestAnimationFrame(() => actionRequiredRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }, [pendingConfirm, pendingInput]);

  const createBrowserSession = useCallback(async () => {
    setCreatingSession(true);
    try {
      const nextSession = await sessionsApi.createSession("协作浏览器任务", newWorkspace);
      setSessions((previous) => [nextSession, ...previous]);
      await loadSession(nextSession.session_id);
      setSessionMenuOpen(false);
      setNotice("已创建浏览器任务。后续网页操作会保留在这个对话和工作空间中。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法创建浏览器任务");
    } finally {
      setCreatingSession(false);
    }
  }, [loadSession, newWorkspace]);

  const sendTask = useCallback(async () => {
    const text = task.trim();
    if (!text || !sessionId) return;
    setSending(true);
    setNotice("");
    setPendingConfirm(null);
    setPendingInput(null);
    try {
      let taskRecord = activeBrowserTask;
      if (!taskRecord || !["running", "waiting_for_user", "paused"].includes(taskRecord.status)) {
        taskRecord = await sessionsApi.createBrowserTask(sessionId, text, browserState.url);
        setBrowserTasks((items) => [taskRecord!, ...items]);
        setActiveBrowserTask(taskRecord);
      }
      await sessionsApi.createBrowserTaskEvent(sessionId, taskRecord.id, {
        event_type: "prompt_sent",
        detail: "AI browser instruction sent",
      });
      await sessionsApi.sendPrompt(sessionId, `${text}

请使用 collab_browser 工具在协作浏览器中完成此任务。每次 observe 后使用返回的 page_version；页面版本过期时必须重新 observe。遇到登录、验证码、二维码、MFA 或敏感数据输入时，必须调用 collab_browser_wait_for_user 并等待用户。禁止绕过人机验证。`);
      setTask("");
      setNotice("AI 正在处理，回复会显示在这里。");
    } catch (reason) {
      setSending(false);
      setError(reason instanceof Error ? reason.message : "无法发送浏览器任务");
    }
  }, [activeBrowserTask, browserState.url, sessionId, task]);

  const handleConfirm = useCallback(async (approved: boolean) => {
    if (!sessionId || !pendingConfirm?.confirm_id) return;
    try {
      await sessionsApi.confirmTool(sessionId, pendingConfirm.confirm_id, approved);
      setMessages((prev) => [
        ...prev,
        {
          id: pendingConfirm.id,
          role: "tool_confirm",
          content: approved ? "已批准" : "已拒绝",
          tool_name: pendingConfirm.tool_name,
          confirmed: approved,
        },
      ]);
      setPendingConfirm(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "确认失败");
    }
  }, [sessionId, pendingConfirm]);

  const handleInput = useCallback(async (answer: string) => {
    if (!sessionId || !pendingInput?.confirm_id) return;
    try {
      await sessionsApi.submitInput(sessionId, pendingInput.confirm_id, answer);
      setMessages((prev) => [
        ...prev,
        { id: pendingInput.id, role: "user", content: answer },
      ]);
      setPendingInput(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "提交失败");
    }
  }, [sessionId, pendingInput]);

  const handleAbort = useCallback(async () => {
    if (!sessionId) return;
    try {
      await sessionsApi.abortSession(sessionId);
      setSending(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "中止失败");
    }
  }, [sessionId]);

  const action = useCallback((name: BrowserAction) => {
    void window.electronAPI?.collaborationBrowserAction?.(name).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : "浏览器操作失败");
    });
  }, []);

  if (!available) {
    return (
      <div className="h-full overflow-auto bg-[var(--bg-primary)] p-6 sm:p-10">
        <div className="mx-auto max-w-2xl rounded-2xl border border-[var(--border)] bg-[var(--bg-secondary)] p-8 shadow-[var(--shadow-md)]">
          <Globe2 size={34} className="mb-4 text-[var(--brand)]" />
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">协作浏览器仅在桌面版可用</h1>
          <p className="mt-3 leading-7 text-sm text-[var(--text-secondary)]">
            此功能会在 CrabAgent 内打开一个真实浏览器会话。你可以亲自处理登录、二维码、验证码和多因素验证，随后让 AI 在同一登录状态下继续工作。
          </p>
          <div className="mt-6 rounded-xl border border-[var(--warning-border)] bg-[var(--warning-bg)] px-4 py-3 text-sm text-[var(--text-secondary)]">
            请从 Electron 桌面应用打开此页面；普通 Web 浏览器无法安全地嵌入需要登录的网站。
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-[var(--bg-primary)]">
      <header className="shrink-0 border-b border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2.5 sm:px-5">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--brand-bg)] text-[var(--brand)]">
            <Globe2 size={17} />
          </div>
          <div className="min-w-0">
            <h1 className="truncate text-sm font-semibold text-[var(--text-primary)]">协作浏览器</h1>
            <p className="hidden text-xs text-[var(--text-tertiary)] sm:block">你和 AI 共享同一个网站登录状态</p>
          </div>
          <div className="ml-auto flex items-center gap-1 text-xs text-[var(--text-tertiary)]">
            {browserState.loading ? <Loader2 size={13} className="animate-spin" /> : <ShieldCheck size={13} className="text-[var(--success)]" />}
            <span className="hidden sm:inline">{browserState.loading ? "加载中" : "人工验证由你完成"}</span>
          </div>
        </div>
        <form className="mt-2 flex items-center gap-1.5" onSubmit={(event) => { event.preventDefault(); void navigate(); }}>
          <button type="button" onClick={() => action("back")} disabled={!browserState.canGoBack} className="browser-control" title="后退"><ArrowLeft size={15} /></button>
          <button type="button" onClick={() => action("forward")} disabled={!browserState.canGoForward} className="browser-control" title="前进"><ArrowRight size={15} /></button>
          <button type="button" onClick={() => action(browserState.loading ? "stop" : "reload")} className="browser-control" title={browserState.loading ? "停止" : "刷新"}>
            {browserState.loading ? <Square size={13} /> : <RefreshCw size={14} />}
          </button>
          <div className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-2.5 focus-within:border-[var(--brand-border)]">
            <ShieldCheck size={14} className="shrink-0 text-[var(--brand)]" />
            <input
              value={address}
              onFocus={() => { addressEditingRef.current = true; }}
              onBlur={() => { addressEditingRef.current = false; }}
              onChange={(event) => setAddress(event.target.value)}
              onKeyDownCapture={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  event.stopPropagation();
                  void navigate();
                }
              }}
              className="min-w-0 flex-1 bg-transparent py-1.5 text-sm text-[var(--text-primary)] outline-none"
              aria-label="网站地址"
            />
          </div>
          <button type="submit" className="rounded-lg bg-[var(--brand)] px-3 py-1.5 text-xs font-medium text-[var(--text-on-brand)] transition-colors hover:bg-[var(--brand-hover)]">打开</button>
        </form>
      </header>



      <div className="flex min-h-0 flex-1">
        <main className="relative z-0 min-w-0 flex-1 bg-white pointer-events-auto">
          <div ref={hostRef} className="absolute inset-0" />
        </main>
        <aside className="hidden w-80 shrink-0 flex-col border-l border-[var(--border)] bg-[var(--bg-secondary)] lg:flex">
          <div className="border-b border-[var(--border)] p-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-[var(--text-primary)]"><ShieldCheck size={16} className="text-[var(--brand)]" /> 协作控制台</div>
            <p className="mt-1 text-xs leading-5 text-[var(--text-secondary)]">在这里切换对话和工作空间；中间网页始终保持完整可见。</p>
          </div>
          <div className="shrink-0 border-b border-[var(--border)]">
            <button
              type="button"
              onClick={() => setContextPanelCollapsed((v) => !v)}
              className="flex w-full items-center gap-1.5 px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)] hover:bg-[var(--bg-tertiary)]"
            >
              {contextPanelCollapsed ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
              <span>对话与工作空间</span>
              <span className="ml-auto truncate text-[10px] font-normal normal-case tracking-normal text-[var(--text-secondary)]">
                {session?.title || "未选择"}
              </span>
            </button>
            {!contextPanelCollapsed && (
              <div className="space-y-3 px-3 pb-3">
                <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-primary)] p-3">
                  <div className="flex rounded-lg bg-[var(--bg-tertiary)] p-0.5">
                    {([
                      ["browser", "浏览器"],
                      ["workspace", "项目内"],
                      ["all", "全部"],
                    ] as [SessionScope, string][]).map(([scope, label]) => (
                      <button key={scope} type="button" onClick={() => {
                        setSessionScope(scope);
                        setSessionQuery("");
                        void refreshSessions(workspaceFilter, scope).catch(() => {});
                      }} className={`flex-1 rounded-md px-1.5 py-1 text-[10px] ${sessionScope === scope ? "bg-[var(--bg-secondary)] font-medium text-[var(--brand)] shadow-sm" : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"}`}>{label}</button>
                    ))}
                  </div>
                  <input value={sessionQuery} onChange={(event) => setSessionQuery(event.target.value)} placeholder="搜索对话" className="mt-2 w-full rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-2 py-1.5 text-xs text-[var(--text-primary)] outline-none focus:border-[var(--brand-border)]" />
                  <div className="mt-2 max-h-40 overflow-y-auto rounded-lg border border-[var(--border)] p-1">
                    {sessions.filter((item) => {
                      const needle = sessionQuery.trim().toLowerCase();
                      return !needle || `${item.title} ${item.workspace}`.toLowerCase().includes(needle);
                    }).slice(0, 30).map((item) => (
                      <button key={item.session_id} type="button" onClick={() => {
                        if (item.session_id !== sessionId) void loadSession(item.session_id).catch((reason) => setError(reason instanceof Error ? reason.message : "无法切换对话"));
                      }} className={`flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-[11px] ${item.session_id === sessionId ? "bg-[var(--brand-bg)] text-[var(--brand)]" : "text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]"}`}>
                        <History size={11} className="shrink-0" /><span className="min-w-0 flex-1 truncate">{item.title || "未命名对话"}</span>
                      </button>
                    ))}
                  </div>
                </div>
                <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-primary)] p-3">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">工作空间</p>
                  <div className="mt-2"><WorkspaceSwitcher current={workspaceFilter} onChange={(workspace) => {
                    setWorkspaceFilter(workspace); setNewWorkspace(workspace); setSessionQuery(""); void refreshSessions(workspace, sessionScope).catch(() => {});
                  }} /></div>
                  {session && <p className="mt-2 flex items-center gap-1 text-[11px] text-[var(--text-secondary)]"><FolderOpen size={11} /> 当前对话：{workspaceName(session.workspace)}</p>}
                  <button type="button" onClick={() => setSessionMenuOpen((open) => !open)} className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-[var(--brand)]"><Plus size={12} /> 新建浏览器任务</button>
                  {sessionMenuOpen && <div className="mt-2 flex flex-col gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-2"><WorkspaceSwitcher current={newWorkspace} onChange={setNewWorkspace} /><button type="button" onClick={() => void createBrowserSession()} disabled={creatingSession} className="rounded-md bg-[var(--brand)] px-2 py-1.5 text-xs font-medium text-[var(--text-on-brand)] disabled:opacity-50">{creatingSession ? "创建中…" : "创建并使用"}</button></div>}
                </div>
              </div>
            )}
          </div>
          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
            <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-primary)] p-3">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">当前页面</p>
              <p className="mt-1.5 truncate text-sm text-[var(--text-primary)]">{browserState.title || "新标签页"}</p>
              <p className="mt-1 break-all text-[11px] leading-4 text-[var(--text-tertiary)]">{browserState.url}</p>
            </div>
            <div className="rounded-xl border border-[var(--brand-border)] bg-[var(--brand-bg)] p-3 text-xs leading-5 text-[var(--text-secondary)]">
              AI 会在此可见网页中操作。登录、验证码、二维码和敏感信息请由你直接完成；AI 不会读取密码或验证码。
            </div>
            {activeBrowserTask && (
              <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-primary)] p-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">任务时间线</p>
                  <span className="rounded-full bg-[var(--brand-bg)] px-1.5 py-0.5 text-[10px] text-[var(--brand)]">{activeBrowserTask.status}</span>
                </div>
                <p className="mt-1 text-xs leading-5 text-[var(--text-primary)]">{activeBrowserTask.goal}</p>
                <div className="mt-2 max-h-36 space-y-1.5 overflow-y-auto">
                  {taskEvents.length === 0 ? (
                    <p className="text-[11px] text-[var(--text-tertiary)]">正在记录安全操作和人工接力步骤。</p>
                  ) : taskEvents.slice(-8).map((event) => (
                    <div key={event.id} className="flex gap-1.5 text-[11px] leading-4 text-[var(--text-secondary)]">
                      <span className={event.risk === "high" ? "text-[var(--warning)]" : "text-[var(--success)]"}>●</span>
                      <span className="min-w-0 break-words">{event.detail}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {notice && <p className="text-xs leading-5 text-[var(--success)]">{notice}</p>}

            <div className="flex items-center gap-2 text-xs font-medium text-[var(--text-tertiary)]">
              <span>近期协作动态</span>
              {sending && <Loader2 size={12} className="animate-spin" />}
              {sessionId && sending && (
                <button type="button" onClick={() => void handleAbort()} className="ml-auto inline-flex items-center gap-1 rounded-md bg-[var(--danger-bg)] px-2 py-0.5 text-[var(--danger)] hover:bg-[var(--danger-border)]">
                  <Square size={10} /> 中止
                </button>
              )}
            </div>

            {!activityLoaded && sessionId && (
              <p className="text-[11px] text-[var(--text-tertiary)]">正在载入最近协作记录…</p>
            )}
            <div className="flex flex-col gap-2 empty:hidden">
              {messages.map((m, idx) => (
                <div key={m.id || idx} className={`rounded-xl border p-2.5 text-xs leading-5 ${
                  m.role === "assistant" || m.role === "thinking"
                    ? "border-[var(--border)] bg-[var(--bg-primary)] text-[var(--text-primary)]"
                    : m.role === "error"
                      ? "border-[var(--danger-border)] bg-[var(--danger-bg)] text-[var(--danger)]"
                      : "border-[var(--brand-border)] bg-[var(--brand-bg)] text-[var(--text-secondary)]"
                }`}>
                  {m.role === "tool_call" && (
                    <div className="mb-1 flex items-center gap-1 font-medium text-[var(--brand)]">
                      <span>🔧 {m.tool_name || "tool"}</span>
                    </div>
                  )}
                  {m.role === "tool_result" && (
                    <div className="mb-1 font-medium text-[var(--success)]">✅ 工具结果</div>
                  )}
                  {m.role === "thinking" && (
                    <div className="mb-1 font-medium text-[var(--text-tertiary)]">🤔 思考中</div>
                  )}
                  <div className="whitespace-pre-wrap break-words">{m.content}</div>
                  {m.role === "tool_call" && m.content && (
                    <div className="mt-1 text-[10px] text-[var(--text-tertiary)]">
                      {(() => {
                        try {
                          const parsed = JSON.parse(m.content);
                          return parsed.name ? `调用: ${parsed.name}` : m.content;
                        } catch {
                          return m.content;
                        }
                      })()}
                    </div>
                  )}
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>

            {pendingConfirm && (
              <div ref={actionRequiredRef} className="rounded-xl border border-[var(--warning-border)] bg-[var(--warning-bg)] p-3">
                <p className="text-xs font-semibold text-[var(--text-primary)]">AI 请求执行工具</p>
                <p className="mt-1 text-xs text-[var(--text-secondary)]">{pendingConfirm.tool_name}</p>
                <p className="mt-1 text-[11px] leading-4 text-[var(--text-tertiary)] break-all">{pendingConfirm.args_summary}</p>
                <div className="mt-2 flex gap-2">
                  <button type="button" onClick={() => handleConfirm(true)} className="inline-flex flex-1 items-center justify-center gap-1 rounded-lg bg-[var(--success)] px-2 py-1 text-xs font-medium text-white hover:opacity-90">
                    <Check size={12} /> 允许
                  </button>
                  <button type="button" onClick={() => handleConfirm(false)} className="inline-flex flex-1 items-center justify-center gap-1 rounded-lg bg-[var(--danger)] px-2 py-1 text-xs font-medium text-white hover:opacity-90">
                    <X size={12} /> 拒绝
                  </button>
                </div>
              </div>
            )}

            {pendingInput && (
              <div ref={actionRequiredRef} className="rounded-xl border border-[var(--brand-border)] bg-[var(--brand-bg)] p-3">
                <p className="text-xs font-semibold text-[var(--text-primary)]">AI 需要你继续</p>
                <p className="mt-1 text-xs text-[var(--text-secondary)]">{pendingInput.content}</p>
                <div className="mt-2 flex flex-col gap-2">
                  {pendingInput.options && pendingInput.options.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {pendingInput.options.map((option) => (
                        <button
                          key={option}
                          type="button"
                          onClick={() => handleInput(option)}
                          className="rounded-lg border border-[var(--brand-border)] bg-[var(--bg-primary)] px-3 py-1.5 text-xs text-[var(--text-primary)] hover:bg-[var(--brand-bg)]"
                        >
                          {option}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <form onSubmit={(e) => { e.preventDefault(); const input = (e.currentTarget.elements.namedItem("input") as HTMLInputElement); if (input.value) handleInput(input.value); }} className="flex gap-2">
                      <input name="input" type="text" autoFocus className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1 text-xs text-[var(--text-primary)] outline-none focus:border-[var(--brand-border)]" />
                      <button type="submit" className="rounded-lg bg-[var(--brand)] px-2 py-1 text-xs font-medium text-[var(--text-on-brand)]">发送</button>
                    </form>
                  )}
                </div>
              </div>
            )}
          </div>
        </aside>
      </div>
      <div className="shrink-0 border-t border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2.5 lg:pr-[20rem]">
        <div className="flex items-end gap-2 rounded-xl border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 shadow-[var(--shadow-sm)] focus-within:border-[var(--brand-border)]">
          <textarea
            value={task}
            onChange={(event) => setTask(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                void sendTask();
              }
            }}
            placeholder={sessionId ? "告诉 AI 要在这个网站完成什么…" : "请先选择或创建一个对话…"}
            disabled={sending || !sessionId}
            rows={1}
            className="max-h-28 min-h-8 flex-1 resize-none bg-transparent py-1 text-sm leading-6 text-[var(--text-primary)] outline-none placeholder:text-[var(--text-tertiary)]"
          />
          <button
            type="button"
            onClick={() => void sendTask()}
            disabled={sending || !sessionId || !task.trim()}
            className="mb-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--brand)] text-[var(--text-on-brand)] transition-colors hover:bg-[var(--brand-hover)] disabled:cursor-not-allowed disabled:opacity-40"
            title="发送任务"
          >
            {sending ? <Loader2 size={15} className="animate-spin" /> : <SendHorizontal size={15} />}
          </button>
        </div>
        <p className="mt-1.5 px-1 text-[11px] text-[var(--text-tertiary)]">Enter 发送，Shift + Enter 换行；登录、验证码和付款确认请由你在网页中完成。</p>
      </div>
      {error && <div className="shrink-0 border-t border-[var(--danger-border)] bg-[var(--danger-bg)] px-4 py-2 text-xs text-[var(--danger)]">{error}</div>}
      <style>{`.browser-control { display: inline-flex; height: 30px; width: 30px; align-items: center; justify-content: center; border-radius: 8px; color: var(--text-secondary); transition: background-color 150ms, color 150ms; } .browser-control:hover:not(:disabled) { background: var(--bg-tertiary); color: var(--text-primary); } .browser-control:disabled { cursor: not-allowed; opacity: .35; }`}</style>
    </div>
  );
}

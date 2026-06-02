import { useState, useEffect, useCallback, useRef } from "react";
import {
  Paperclip,
  Bot,
  ArrowUp,
  Square,
  FolderOpen,
  PanelRightOpen,
  PanelRightClose,
  LogOut,
  Sparkles,
  MessageSquare,
  Code,
  Compass,
  X,
  Menu,
  Loader2,
} from "lucide-react";
import * as sessionsApi from "../api/sessions";
import * as providersApi from "../api/providers";
import * as mcpServersApi from "../api/mcpServers";
import { McpServer, McpServerStatus } from "../api/mcpServers";
import { Session } from "../api/sessions";
import {
  AgentProfile as AgentProfileType,
  listAgentProfiles,
} from "../api/agents";
import SessionList from "../components/SessionList";
import ChatPanel from "../components/ChatPanel";
import ProviderPanel from "../components/ProviderPanel";
import McpServerPanel from "../components/McpServerPanel";
import McpStatusBar from "../components/McpStatusBar";
import BranchSelector from "../components/BranchSelector";
import FileBrowser from "../components/FileBrowser";
import TodoWidget from "../components/TodoWidget";
import { NotificationBell } from "../components/NotificationBell";
import { ScheduledTaskPanel } from "../components/ScheduledTaskPanel";
import { AgentTeamPanel } from "../components/AgentTeamPanel";
import { TaskBoard } from "../components/TaskBoard";
import { AgentBar } from "../components/AgentBar";
import { DelegateModal } from "../components/DelegateModal";
import { ResultCompare } from "../components/ResultCompare";
import { Modal, Button, Textarea } from "../components/ui";
import { useChatState } from "../hooks/useChatState";
import { useTaskBoard } from "../hooks/useTaskBoard";
import { useModelSelector } from "../hooks/useModelSelector";
import { cn } from "../lib/cn";

interface Props {
  onLogout: () => void;
}

const STARTER_PROMPTS = [
  { icon: <Code size={14} />, label: "Debug an error", prompt: "Help me debug this error: " },
  { icon: <Compass size={14} />, label: "Explain a concept", prompt: "Explain how " },
  { icon: <Sparkles size={14} />, label: "Brainstorm ideas", prompt: "Brainstorm some ideas for " },
  { icon: <MessageSquare size={14} />, label: "Write a doc", prompt: "Write documentation for " },
];

export default function ChatPage({ onLogout }: Props) {
  const { taskBoardTasks, handleTaskBoardEvent, clearTaskBoard } =
    useTaskBoard();

  const {
    sessions,
    setSessions,
    activeSession,
    messages,
    setMessages,
    sending,
    setSending,
    connected,
    activeBranch,
    replaying,
    replayProgress,
    todoRefreshKey,
    bottomRef,
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
  } = useChatState(handleTaskBoardEvent);

  const {
    providers,
    catalog,
    models,
    providersLoading,
    modelsLoading,
    modelsError,
    selectedModel,
    setSelectedModel,
    setProviders,
    setProvidersLoading,
  } = useModelSelector();

  const [showProviders, setShowProviders] = useState(false);
  const [showMcpServers, setShowMcpServers] = useState(false);
  const [showScheduledTasks, setShowScheduledTasks] = useState(false);
  const [showAgentTeam, setShowAgentTeam] = useState(false);
  const [viewingSubAgent, setViewingSubAgent] = useState<string | null>(null);
  const [showDelegate, setShowDelegate] = useState(false);
  const [showResultCompare, setShowResultCompare] = useState(false);
  const [showFiles, setShowFiles] = useState(false);
  const [input, setInput] = useState("");
  const [pendingImages, setPendingImages] = useState<string[]>([]);
  const [agentProfiles, setAgentProfiles] = useState<AgentProfileType[]>([]);
  const [selectedAgent, setSelectedAgent] = useState("default");
  const [mcpServers, setMcpServers] = useState<McpServer[]>([]);
  const [mcpStatus, setMcpStatus] = useState<McpServerStatus[]>([]);
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    mcpServersApi.listMcpServers().then(setMcpServers);
    mcpServersApi.getMcpStatus().then(setMcpStatus);
    listAgentProfiles().then(setAgentProfiles).catch(() => {});
  }, []);

  useEffect(() => {
    const interval = setInterval(() => {
      mcpServersApi.getMcpStatus().then(setMcpStatus).catch(() => {});
    }, 60000);
    return () => clearInterval(interval);
  }, []);

  // Global keyboard shortcuts: / focus input, Cmd+K new session
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const isTyping =
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable;
      if (e.key === "/" && !isTyping) {
        e.preventDefault();
        inputRef.current?.focus();
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        onNewSession();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedModel, models]);

  const onSelectSession = useCallback(
    async (session: Session) => {
      const model = await selectSession(session, selectedModel, models);
      setSelectedModel(model);
      clearTaskBoard();
    },
    [selectSession, selectedModel, models, setSelectedModel, clearTaskBoard],
  );

  const onNewSession = useCallback(async () => {
    const model = await newSession(selectedModel, models);
    setSelectedModel(model);
    clearTaskBoard();
  }, [newSession, selectedModel, models, setSelectedModel, clearTaskBoard]);

  const onSelectSessionById = useCallback(
    async (sessionId: string) => {
      const model = await selectSessionById(sessionId, selectedModel, models);
      setSelectedModel(model);
    },
    [selectSessionById, selectedModel, models, setSelectedModel],
  );

  const processImageFile = (file: File) => {
    if (pendingImages.length >= 5) return;
    if (file.size > 5 * 1024 * 1024) return;
    if (!file.type.startsWith("image/")) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      const dataUrl = e.target?.result as string;
      if (dataUrl) setPendingImages((prev) => [...prev, dataUrl]);
    };
    reader.readAsDataURL(file);
  };

  const handleImagePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (const item of Array.from(items)) {
      if (item.type.startsWith("image/")) {
        e.preventDefault();
        const file = item.getAsFile();
        if (file) processImageFile(file);
        return;
      }
    }
  };

  const handleImageUpload = () => {
    const el = document.createElement("input");
    el.type = "file";
    el.accept = "image/*";
    el.multiple = true;
    el.onchange = (e) => {
      const files = (e.target as HTMLInputElement).files;
      if (files) Array.from(files).forEach(processImageFile);
    };
    el.click();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const files = e.dataTransfer?.files;
    if (files) Array.from(files).forEach(processImageFile);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const parseAgentMentions = (text: string, profiles: AgentProfileType[]) => {
    const enabled = profiles.filter((p) => p.enabled);
    const matches: AgentProfileType[] = [];
    const tokens = text.split(/\s+/);
    for (const p of enabled) {
      if (tokens.includes(`@${p.name}`)) matches.push(p);
    }
    return matches;
  };

  const handleSend = async () => {
    if ((!input.trim() && pendingImages.length === 0) || !activeSession || sending)
      return;
    let text = input.trim();
    const images = [...pendingImages];
    setInput("");
    setPendingImages([]);
    setMessages((prev) => [
      ...prev,
      {
        id: `u-${Date.now()}`,
        role: "user",
        content: text,
        images: images.length > 0 ? images : undefined,
      },
    ]);
    setSending(true);
    try {
      const mentions = parseAgentMentions(text, agentProfiles);
      if (mentions.length > 0) {
        const mainText = text.replace(/@\w+/g, "").replace(/\s+/g, " ").trim();
        if (mentions.length === 1) {
          const taskText = mainText || "Please complete this task";
          text = `[delegate_task] agent_name="${mentions[0].name}" task="${taskText.replace(/"/g, "'")}"\n\nOriginal request: ${text}`;
        } else {
          const tasksJson = mentions.map((m) => ({
            agent_name: m.name,
            task: mainText || "Please complete this task",
          }));
          text = `[delegate_parallel] tasks=${JSON.stringify(tasksJson)}\n\nOriginal request: ${text}`;
        }
      }
      await sessionsApi.sendPrompt(
        activeSession.session_id,
        text || "请分析这张图片",
        selectedModel,
        images.length > 0 ? images : undefined,
        selectedAgent,
      );
    } catch {
      setSending(false);
    }
  };

  const handleToolConfirm = async (confirmId: string, approved: boolean) => {
    if (!activeSession) return;
    setMessages((prev) =>
      prev.map((m) =>
        m.confirm_id === confirmId ? { ...m, confirmed: approved } : m,
      ),
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
        m.confirm_id === inputId ? { ...m, confirmed: true, content: answer } : m,
      ),
    );
    try {
      await sessionsApi.submitInput(activeSession.session_id, inputId, answer);
    } catch {
      // ignore
    }
  };

  const handleDelegateFromModal = async (
    tasks: { agent_name: string; task: string }[],
  ) => {
    if (!activeSession || sending) return;
    setShowDelegate(false);
    const names = tasks.map((t) => `@${t.agent_name}`).join(" ");
    const taskDesc =
      tasks.length === 1
        ? tasks[0].task
        : tasks.map((t) => `${t.agent_name}: ${t.task}`).join("; ");
    setMessages((prev) => [
      ...prev,
      {
        id: `u-${Date.now()}`,
        role: "user",
        content: `${names} ${taskDesc}`,
      },
    ]);
    setSending(true);
    try {
      let promptText: string;
      if (tasks.length === 1) {
        promptText = `[delegate_task] agent_name="${tasks[0].agent_name}" task="${tasks[0].task.replace(/"/g, "'")}"`;
      } else {
        promptText = `[delegate_parallel] tasks=${JSON.stringify(tasks)}`;
      }
      await sessionsApi.sendPrompt(activeSession.session_id, promptText, selectedModel);
    } catch {
      setSending(false);
    }
  };

  const handleAgentBarClick = (agent: AgentProfileType) => {
    setInput((prev) => {
      const mention = `@${agent.name} `;
      if (prev.includes(mention.trim())) return prev;
      return prev ? `${prev} ${mention}` : mention;
    });
    inputRef.current?.focus();
  };

  const handleExportReport = async () => {
    if (!activeSession) return;
    const token = localStorage.getItem("crab_token") || "";
    const resp = await fetch(
      `/api/sessions/${encodeURIComponent(activeSession.session_id)}/report?token=${encodeURIComponent(token)}`,
    );
    const text = await resp.text();
    const blob = new Blob([text], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `crabagent-report-${activeSession.session_id.slice(0, 8)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const completedTasks = taskBoardTasks.filter((t) => t.status === "done");

  return (
    <div className="flex h-full overflow-hidden bg-[var(--bg-primary)]">
      <SessionList
        sessions={sessions}
        activeId={activeSession?.session_id || null}
        onSelect={onSelectSession}
        onNew={onNewSession}
        onDelete={handleDeleteSession}
        onOpenProviders={() => setShowProviders(true)}
        onOpenMcpServers={() => setShowMcpServers(true)}
        onOpenScheduledTasks={() => setShowScheduledTasks(true)}
        onOpenAgentTeam={() => setShowAgentTeam(true)}
        mobileOpen={mobileSidebarOpen}
        onMobileClose={() => setMobileSidebarOpen(false)}
      />

      <div className="flex-1 flex flex-col min-w-0">
        {/* Toolbar */}
        <div
          className="flex items-center gap-1 px-3 h-11 border-b border-[var(--border)] bg-[var(--bg-secondary)]"
        >
          <Button
            size="icon"
            variant="ghost"
            onClick={() => setMobileSidebarOpen(true)}
            title="Conversations"
            className="md:hidden"
          >
            <Menu size={16} />
          </Button>
          <div className="flex-1 min-w-0">
            {activeSession && (
              <BranchSelector
                sessionId={activeSession.session_id}
                activeBranch={activeBranch}
                onSwitch={handleSwitchBranch}
                onReplay={startReplay}
              />
            )}
          </div>
          <NotificationBell onSwitchSession={onSelectSessionById} />
          {completedTasks.length > 0 && (
            <Button
              size="icon"
              variant="ghost"
              onClick={() => setShowResultCompare(true)}
              title="View agent results"
              className="text-[var(--accent-2)] hover:text-[var(--accent-2)] hover:bg-[var(--accent-2-bg)]"
            >
              <Bot size={15} />
            </Button>
          )}
          <Button
            size="icon"
            variant="ghost"
            onClick={() => setShowFiles((v) => !v)}
            title={showFiles ? "Hide file browser" : "Show file browser"}
            className={showFiles ? "text-[var(--brand)] bg-[var(--brand-bg)]" : ""}
          >
            {showFiles ? <PanelRightClose size={15} /> : <PanelRightOpen size={15} />}
          </Button>
          <Button
            size="icon"
            variant="ghost"
            onClick={() => setShowLogoutConfirm(true)}
            title="Logout"
            className="text-[var(--text-tertiary)] hover:text-[var(--danger)] hover:bg-[var(--danger-bg)]"
          >
            <LogOut size={15} />
          </Button>
        </div>

        {activeSession ? (
          <>
            {replaying && replayProgress.total > 0 && (
              <div className="px-4 pt-2 pb-1 border-b border-[var(--border)] bg-[var(--bg-secondary)]">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-[var(--success)] flex items-center gap-1.5">
                    <Sparkles size={11} className="animate-pulse" />
                    Replaying branch
                  </span>
                  <span className="text-xs text-[var(--text-tertiary)] font-mono">
                    {replayProgress.current} / {replayProgress.total}
                  </span>
                </div>
                <div className="h-1 rounded-full overflow-hidden bg-[var(--bg-tertiary)]">
                  <div
                    className="h-full transition-all duration-200 rounded-full bg-gradient-to-r from-[var(--success)] to-[var(--accent)]"
                    style={{
                      width: `${(replayProgress.current / replayProgress.total) * 100}%`,
                    }}
                  />
                </div>
              </div>
            )}

            <ChatPanel
              ref={bottomRef}
              messages={messages}
              connected={connected}
              onToolConfirm={handleToolConfirm}
              onUserInput={handleUserInput}
              onBranch={handleBranch}
              replaying={replaying}
              externalSubAgentId={viewingSubAgent}
              onSubAgentModalClose={() => setViewingSubAgent(null)}
              getSubAgentContent={getSubAgentContent}
            />

            <McpStatusBar status={mcpStatus} />

            <div
              className="px-3 sm:px-4 pb-3 pt-2"
              onDrop={handleDrop}
              onDragOver={handleDragOver}
            >
              <AgentBar onAgentClick={handleAgentBarClick} />

              {/* Agent + Model selectors */}
              <div className="mb-2 flex items-center gap-2 flex-wrap">
                {agentProfiles.length > 0 && (
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] text-[var(--text-tertiary)]">
                      Agent
                    </span>
                    <select
                      value={selectedAgent}
                      onChange={async (e) => {
                        const agent = e.target.value;
                        setSelectedAgent(agent);
                        if (activeSession) {
                          try {
                            await sessionsApi.switchAgent(
                              activeSession.session_id,
                              agent,
                            );
                          } catch {
                            // ignore
                          }
                        }
                      }}
                      className="text-xs h-7 px-2 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--brand)] focus:ring-2 focus:ring-[var(--brand)]/30"
                    >
                      <option value="default">🦀 default</option>
                      {agentProfiles.map((a) => (
                        <option key={a.name} value={a.name}>
                          {a.icon || "🤖"} {a.display_name}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
                {modelsLoading ? (
                  <div className="flex items-center gap-1.5">
                    <Loader2 size={12} className="animate-spin text-[var(--text-tertiary)]" />
                    <span className="text-[11px] text-[var(--text-tertiary)]">Loading models…</span>
                  </div>
                ) : models.length > 0 ? (
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] text-[var(--text-tertiary)]">
                      Model
                    </span>
                    <select
                      value={selectedModel}
                      onChange={(e) => setSelectedModel(e.target.value)}
                      className="text-xs h-7 px-2 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] font-mono focus:outline-none focus:border-[var(--brand)] focus:ring-2 focus:ring-[var(--brand)]/30"
                    >
                      {models.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.id}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : (
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] text-[var(--text-tertiary)]">
                      Model
                    </span>
                    <input
                      type="text"
                      value={selectedModel}
                      onChange={(e) => setSelectedModel(e.target.value)}
                      placeholder="type model id…"
                      className="text-xs h-7 px-2 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] font-mono focus:outline-none focus:border-[var(--brand)] focus:ring-2 focus:ring-[var(--brand)]/30 w-40 placeholder:text-[var(--text-tertiary)]"
                    />
                    {modelsError && (
                      <span
                        className="text-[10px] text-[var(--danger)] cursor-pointer"
                        title={modelsError}
                        onClick={() => window.location.reload()}
                      >
                        Retry
                      </span>
                    )}
                  </div>
                )}
              </div>

              {/* Pending images */}
              {pendingImages.length > 0 && (
                <div className="flex gap-2 mb-2 flex-wrap">
                  {pendingImages.map((img, i) => (
                    <div key={i} className="relative inline-block">
                      <img
                        src={img}
                        className="h-16 w-16 object-cover rounded-lg border border-[var(--border)]"
                        alt=""
                      />
                      <button
                        onClick={() =>
                          setPendingImages((prev) =>
                            prev.filter((_, idx) => idx !== i),
                          )
                        }
                        className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full flex items-center justify-center bg-[var(--danger)] text-white hover:bg-[var(--danger-hover)] transition-colors"
                        aria-label="Remove image"
                      >
                        <X size={11} />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* Input row */}
              <div className="flex gap-2 items-end">
                <Button
                  size="icon"
                  variant="outline"
                  onClick={handleImageUpload}
                  disabled={sending || replaying || pendingImages.length >= 5}
                  title="Attach image"
                  className="h-10 w-10"
                >
                  <Paperclip size={15} />
                </Button>
                <Button
                  size="icon"
                  variant="outline"
                  onClick={() => setShowDelegate(true)}
                  disabled={sending || replaying}
                  title="Delegate to agent team"
                  className="h-10 w-10 text-[var(--accent-2)] hover:text-[var(--accent-2)] hover:bg-[var(--accent-2-bg)] border-[var(--accent-2-border,var(--border))]"
                >
                  <Bot size={15} />
                </Button>
                <Textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleSend();
                    }
                  }}
                  onPaste={handleImagePaste}
                  placeholder="Type a message… (Shift+Enter for newline, / to focus, ⌘K new session)"
                  disabled={sending || replaying}
                  ref={inputRef}
                  autoGrow
                  minRows={1}
                  maxRows={6}
                  className="flex-1 min-h-[40px]"
                />
                {sending ? (
                  <Button
                    variant="danger"
                    onClick={handleAbort}
                    className="h-10 w-10"
                    size="icon"
                    title="Stop"
                  >
                    <Square size={14} fill="currentColor" />
                  </Button>
                ) : (
                  <Button
                    variant="brand"
                    onClick={handleSend}
                    disabled={!input.trim() && pendingImages.length === 0}
                    className="h-10 w-10 shrink-0"
                    size="icon"
                    title="Send"
                  >
                    <ArrowUp size={16} />
                  </Button>
                )}
              </div>
            </div>
          </>
        ) : (
          /* Empty state */
          <div className="flex-1 flex items-center justify-center px-4">
            <div className="text-center max-w-md animate-fade-in">
              <div
                className="w-16 h-16 rounded-2xl mx-auto mb-4 flex items-center justify-center text-3xl shadow-[var(--shadow-md)]"
                style={{
                  background:
                    "linear-gradient(135deg, var(--brand) 0%, var(--brand-active) 100%)",
                }}
              >
                🦀
              </div>
              <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-1">
                Welcome to CrabAgent
              </h2>
              <p className="text-sm text-[var(--text-tertiary)] mb-6">
                Start a conversation or pick a quick template below
              </p>
              <div className="grid grid-cols-2 gap-2 mb-6">
                {STARTER_PROMPTS.map((p, i) => (
                  <button
                    key={i}
                    onClick={() => {
                      onNewSession();
                      setTimeout(() => {
                        setInput(p.prompt);
                        inputRef.current?.focus();
                      }, 100);
                    }}
                    className={cn(
                      "flex items-center gap-2 px-3 py-2.5 rounded-xl text-left",
                      "bg-[var(--bg-secondary)] border border-[var(--border)]",
                      "hover:border-[var(--border-strong)] hover:bg-[var(--bg-tertiary)]",
                      "transition-colors group",
                    )}
                  >
                    <span className="text-[var(--brand)] group-hover:scale-110 transition-transform">
                      {p.icon}
                    </span>
                    <span className="text-xs text-[var(--text-secondary)] group-hover:text-[var(--text-primary)]">
                      {p.label}
                    </span>
                  </button>
                ))}
              </div>
              <Button variant="brand" onClick={onNewSession}>
                <Sparkles size={14} /> Start New Conversation
              </Button>
            </div>
          </div>
        )}
      </div>

      <FileBrowser
        collapsed={!showFiles}
        onToggle={() => setShowFiles((v) => !v)}
        sessionId={activeSession?.session_id || null}
      />

      <TaskBoard
        tasks={taskBoardTasks}
        onTaskClick={(t) => setViewingSubAgent(t.subId)}
      />

      <TodoWidget
        sessionId={activeSession?.session_id || null}
        refreshKey={todoRefreshKey}
      />

      {/* No provider overlay */}
      {!providersLoading && providers.length === 0 && (
        <Modal
          open={true}
          onOpenChange={() => {}}
          title="Welcome to CrabAgent"
          description="Set up your first LLM provider to get started"
          size="sm"
          hideClose
          disableBackdropClose
          footer={
            <Button variant="brand" onClick={() => setShowProviders(true)}>
              Add Provider
            </Button>
          }
        >
          <div className="text-center py-2">
            <div className="text-4xl mb-3">🔑</div>
            <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
              CrabAgent needs at least one LLM provider to function. Add your API
              key to start chatting.
            </p>
          </div>
        </Modal>
      )}

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

      {showScheduledTasks && (
        <ScheduledTaskPanel
          onClose={() => setShowScheduledTasks(false)}
          onSwitchSession={onSelectSessionById}
        />
      )}

      {showAgentTeam && (
        <AgentTeamPanel onClose={() => setShowAgentTeam(false)} />
      )}

      {showDelegate && activeSession && (
        <DelegateModal
          onClose={() => setShowDelegate(false)}
          onDelegate={handleDelegateFromModal}
        />
      )}

      {showResultCompare && taskBoardTasks.length > 0 && (
        <ResultCompare
          tasks={taskBoardTasks}
          onClose={() => setShowResultCompare(false)}
          onExport={handleExportReport}
        />
      )}

      {/* Logout confirmation */}
      <Modal
        open={showLogoutConfirm}
        onOpenChange={setShowLogoutConfirm}
        title="Sign out?"
        description="You'll need to log in again to continue."
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setShowLogoutConfirm(false)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={onLogout}>
              Sign Out
            </Button>
          </>
        }
      >
        <div className="text-center py-2">
          <LogOut size={32} className="mx-auto text-[var(--danger)] mb-2" />
        </div>
      </Modal>
    </div>
  );
}

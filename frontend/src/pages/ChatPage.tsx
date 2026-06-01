import { useState, useEffect, useCallback } from "react";
import * as sessionsApi from "../api/sessions";
import * as providersApi from "../api/providers";
import * as mcpServersApi from "../api/mcpServers";
import { McpServer, McpServerStatus } from "../api/mcpServers";
import { Session } from "../api/sessions";
import { AgentProfile as AgentProfileType, listAgentProfiles } from "../api/agents";
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
import { useChatState } from "../hooks/useChatState";
import { useTaskBoard } from "../hooks/useTaskBoard";
import { useModelSelector } from "../hooks/useModelSelector";

interface Props {
  onLogout: () => void;
}

export default function ChatPage({ onLogout }: Props) {
  const { taskBoardTasks, handleTaskBoardEvent, clearTaskBoard } = useTaskBoard();

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

  const { providers, catalog, models, providersLoading, selectedModel, setSelectedModel, setProviders, setProvidersLoading } = useModelSelector();

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

  const onSelectSession = useCallback(
    async (session: Session) => {
      const model = await selectSession(session, selectedModel, models);
      setSelectedModel(model);
      clearTaskBoard();
    },
    [selectSession, selectedModel, models, setSelectedModel, clearTaskBoard]
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
    [selectSessionById, selectedModel, models, setSelectedModel]
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
    for (const p of enabled) {
      if (text.includes(`@${p.name}`)) {
        matches.push(p);
      }
    }
    return matches;
  };

  const handleSend = async () => {
    if ((!input.trim() && pendingImages.length === 0) || !activeSession || sending) return;
    let text = input.trim();
    const images = [...pendingImages];
    setInput("");
    setPendingImages([]);
    setMessages((prev) => [...prev, { id: `u-${Date.now()}`, role: "user", content: text, images: images.length > 0 ? images : undefined }]);
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
    setMessages((prev) => prev.map((m) => (m.confirm_id === confirmId ? { ...m, confirmed: approved } : m)));
    try {
      await sessionsApi.confirmTool(activeSession.session_id, confirmId, approved);
    } catch {
      // ignore
    }
  };

  const handleUserInput = async (inputId: string, answer: string) => {
    if (!activeSession) return;
    setMessages((prev) => prev.map((m) => (m.confirm_id === inputId ? { ...m, confirmed: true, content: answer } : m)));
    try {
      await sessionsApi.submitInput(activeSession.session_id, inputId, answer);
    } catch {
      // ignore
    }
  };

  const handleDelegateFromModal = async (tasks: { agent_name: string; task: string }[]) => {
    if (!activeSession || sending) return;
    setShowDelegate(false);
    const names = tasks.map((t) => `@${t.agent_name}`).join(" ");
    const taskDesc = tasks.length === 1 ? tasks[0].task : tasks.map((t) => `${t.agent_name}: ${t.task}`).join("; ");
    setMessages((prev) => [...prev, { id: `u-${Date.now()}`, role: "user", content: `${names} ${taskDesc}` }]);
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
  };

  const handleExportReport = async () => {
    if (!activeSession) return;
    const token = localStorage.getItem("crab_token") || "";
    const resp = await fetch(`/api/sessions/${encodeURIComponent(activeSession.session_id)}/report?token=${encodeURIComponent(token)}`);
    const text = await resp.text();
    const blob = new Blob([text], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `crabagent-report-${activeSession.session_id.slice(0, 8)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex h-full overflow-hidden">
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
      />

      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex items-center border-b" style={{ borderBottom: "1px solid var(--border)" }}>
          <div className="flex-1">
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
          {taskBoardTasks.filter((t) => t.status === "done").length > 0 && (
            <button
              onClick={() => setShowResultCompare(true)}
              className="px-3 py-2 text-sm"
              style={{ color: "#a78bfa" }}
              title="View agent results"
            >
              📋
            </button>
          )}
          <button
            onClick={() => setShowFiles((v) => !v)}
            className="px-3 py-2 text-sm"
            style={{ color: showFiles ? "var(--accent)" : "var(--text-secondary)" }}
            title="Toggle file browser"
          >
            📁
          </button>
          <button
            onClick={onLogout}
            className="px-3 py-2 text-sm"
            style={{ color: "var(--text-secondary)" }}
            title="Logout"
          >
            ⏻
          </button>
        </div>
        {activeSession ? (
          <>
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
            <ChatPanel ref={bottomRef} messages={messages} connected={connected} onToolConfirm={handleToolConfirm} onUserInput={handleUserInput} onBranch={handleBranch} replaying={replaying}
              externalSubAgentId={viewingSubAgent} onSubAgentModalClose={() => setViewingSubAgent(null)} getSubAgentContent={getSubAgentContent} />

            <McpStatusBar status={mcpStatus} />

            <div className="px-4 pb-4" onDrop={handleDrop} onDragOver={handleDragOver}>
              <AgentBar onAgentClick={handleAgentBarClick} />
              {agentProfiles.length > 0 && (
                <div className="mb-2 flex items-center gap-2">
                  <span className="text-xs" style={{ color: "var(--text-secondary)" }}>Agent:</span>
                  <select
                    value={selectedAgent}
                    onChange={async (e) => {
                      const agent = e.target.value;
                      setSelectedAgent(agent);
                      if (activeSession) {
                        try {
                          await sessionsApi.switchAgent(activeSession.session_id, agent);
                        } catch {
                          // ignore
                        }
                      }
                    }}
                    className="text-xs px-2 py-1 rounded outline-none"
                    style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                  >
                    <option value="default">🦀 default (All tools)</option>
                    {agentProfiles.map((a) => (
                      <option key={a.name} value={a.name}>
                        {a.icon || "🤖"} {a.display_name}
                      </option>
                    ))}
                  </select>
                </div>
              )}
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
              {pendingImages.length > 0 && (
                <div className="flex gap-2 mb-2 flex-wrap">
                  {pendingImages.map((img, i) => (
                    <div key={i} className="relative inline-block">
                      <img src={img} className="h-16 w-16 object-cover rounded-lg" style={{ border: "1px solid var(--border)" }} />
                      <button
                        onClick={() => setPendingImages((prev) => prev.filter((_, idx) => idx !== i))}
                        className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full flex items-center justify-center text-xs"
                        style={{ background: "var(--danger)", color: "#fff", fontSize: "10px", lineHeight: 1 }}
                      >
                        ×
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <div className="flex gap-2">
                <button
                  onClick={handleImageUpload}
                  disabled={sending || replaying || pendingImages.length >= 5}
                  className="px-3 py-3 rounded-lg text-sm disabled:opacity-30"
                  style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)", border: "1px solid var(--border)" }}
                  title="Attach image"
                >
                  📎
                </button>
                <button
                  onClick={() => setShowDelegate(true)}
                  disabled={sending || replaying}
                  className="px-3 py-3 rounded-lg text-sm disabled:opacity-30"
                  style={{ background: "var(--bg-secondary)", color: "#a78bfa", border: "1px solid #7c3aed40" }}
                  title="Delegate to agent team"
                >
                  🤖
                </button>
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
                  onPaste={handleImagePaste}
                  placeholder="Type a message... (paste/drag images here)"
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
                    disabled={!input.trim() && pendingImages.length === 0}
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

      <TaskBoard tasks={taskBoardTasks} onTaskClick={(t) => setViewingSubAgent(t.subId)} />

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

      {showScheduledTasks && (
        <ScheduledTaskPanel
          onClose={() => setShowScheduledTasks(false)}
          onSwitchSession={onSelectSessionById}
        />
      )}

      {showAgentTeam && (
        <AgentTeamPanel
          onClose={() => setShowAgentTeam(false)}
        />
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
    </div>
  );
}

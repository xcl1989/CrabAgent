import { useState, useEffect, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import ChatInput from "../components/ChatInput";
import {
  Bot,
  PanelRightOpen,
  PanelRightClose,
  Sparkles,
  MessageSquare,
  Code,
  Compass,
  X,
  Menu,
  Loader2,
  ChevronDown,
  Check,
  LayoutPanelLeft,
  LayoutPanelTop,
  FileText,
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
import NotificationBell from "../components/NotificationBell";
import { ScheduledTaskPanel } from "../components/ScheduledTaskPanel";
import TaskPanel from "../components/TaskPanel";
import EmailPanel from "../components/EmailPanel";
import SkillsPanel from "../components/SkillsPanel";
import { TaskBoard } from "../components/TaskBoard";
import { AgentBar } from "../components/AgentBar";
import { DelegateModal } from "../components/DelegateModal";
import { ResultCompare } from "../components/ResultCompare";
import WorkspaceSwitcher from "../components/WorkspaceSwitcher";
import ModelSelector from "../components/ModelSelector";
import { Modal, Button } from "../components/ui";
import { useChatState } from "../hooks/useChatState";
import { useTaskBoard } from "../hooks/useTaskBoard";
import { useModelSelector } from "../hooks/useModelSelector";
import { cn } from "../lib/cn";
import { DocumentPanel, DocState } from "../components/DocumentPanel";
import { DocOpEvent } from "../components/DocumentTimeline";
import { CodePanel } from "../components/CodePanel";
import { PrototypePanel } from "../components/PrototypePanel";
import { MeetingPanel } from "../components/MeetingPanel";
import { MarkdownPanel } from "../components/MarkdownPanel";
import { SSEEvent } from "../api/events";
import * as documentsApi from "../api/documents";

interface Props {
}

const STARTER_PROMPTS = [
  { icon: <Code size={14} />, labelKey: "chat.debugLabel", promptKey: "chat.debugPrompt" },
  { icon: <Compass size={14} />, labelKey: "chat.explainLabel", promptKey: "chat.explainPrompt" },
  { icon: <Sparkles size={14} />, labelKey: "chat.brainstormLabel", promptKey: "chat.brainstormPrompt" },
  { icon: <MessageSquare size={14} />, labelKey: "chat.writeDocLabel", promptKey: "chat.writeDocPrompt" },
];

export default function ChatPage({ onActiveSessionChange }: { onActiveSessionChange?: (sessionId: string | null) => void }) {
  const { t, i18n } = useTranslation();
  const [workspace, setWorkspace] = useState<string>("");
  const { taskBoardTasks, handleTaskBoardEvent, clearTaskBoard } =
    useTaskBoard();

  const {
    providers,
    catalog,
    models,
    providerModels,
    providersLoading,
    modelsLoading,
    modelsError,
    selectedModel,
    setSelectedModel,
    setProviders,
    setProvidersLoading,
    refreshProviders,
  } = useModelSelector();

  const onAutoLoadSession = useCallback((session: Session) => {
    if (session.model) setSelectedModel(session.model);
    if (session.provider) setSelectedProvider(session.provider);
    if (session.workspace) setWorkspace(session.workspace);
    if (session.agent) setSelectedAgent(session.agent);
  }, [setSelectedModel]);

  // ── Document panel state (must be before useChatState) ─────────
  const [docState, setDocState] = useState<DocState | null>(null);
  const [currentDocPath, setCurrentDocPath] = useState<string | null>(null);

  // ── Document panel width (resizable + persistent) ──────────────
  // Layout: [SessionList 256px] [Chat flex-1] [DocPanel]
  // We must keep chat area >= 380px so the drag handle is always reachable.
  const DOC_PANEL_MIN = 360;
  const DOC_PANEL_DEFAULT = 520;
  const DOC_PANEL_STORAGE_KEY = "crabagent_doc_panel_width";
  const SESSION_LIST_W = 256; // w-64 = 16rem = 256px
  const CHAT_MIN_W = 380;

  /** Dynamic max: viewport minus sidebar minus minimum chat width */
  const docPanelMax = () => window.innerWidth - SESSION_LIST_W - CHAT_MIN_W;

  const [docPanelWidth, setDocPanelWidth] = useState<number>(() => {
    try {
      const saved = localStorage.getItem(DOC_PANEL_STORAGE_KEY);
      if (saved) {
        const w = parseInt(saved, 10);
        if (w >= DOC_PANEL_MIN && w <= docPanelMax()) return w;
      }
    } catch {}
    return Math.min(DOC_PANEL_DEFAULT, docPanelMax());
  });

  const [docPanelMaximized, setDocPanelMaximized] = useState(false);

  // ── Work mode state ────────────────────────────────────────────
  type Mode = "chat" | "work";
  const [mode, setMode] = useState<Mode>(() => {
    try {
      const saved = localStorage.getItem("crabagent_mode");
      if (saved === "work" || saved === "chat") return saved;
    } catch {}
    return "chat";
  });
  const [pendingHighlight, setPendingHighlight] = useState<{ path?: string; text?: string } | null>(null);
  type WorkspaceType = "document" | "code" | "prototype" | "meeting" | "markdown";
  const [workspaceType, setWorkspaceType] = useState<WorkspaceType>("document");
  const [meetingActive, setMeetingActive] = useState(false);
  const [fileTreeRefreshKey, setFileTreeRefreshKey] = useState(0);

  const handleStartMeeting = useCallback(() => {
    setMeetingActive(true);
    setWorkspaceType("meeting");
    setMode("work");
  }, []);

  useEffect(() => {
    localStorage.setItem("crabagent_mode", mode);
  }, [mode]);

  const docPanelWidthRef = useRef(docPanelWidth);
  docPanelWidthRef.current = docPanelWidth;

  const handleDocPanelResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = docPanelWidthRef.current;

    // Full-screen overlay to capture all mouse events (prevents iframe from stealing them)
    const overlay = document.createElement("div");
    overlay.style.cssText =
      "position:fixed;inset:0;z-index:9999;cursor:col-resize;";
    document.body.appendChild(overlay);

    const handleMouseMove = (ev: MouseEvent) => {
      const delta = startX - ev.clientX; // drag left → wider panel
      const maxW = docPanelMax();
      const newWidth = Math.min(maxW, Math.max(DOC_PANEL_MIN, startWidth + delta));
      setDocPanelWidth(newWidth);
    };

    const handleMouseUp = () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
      overlay.remove();
      setDocPanelWidth((w) => {
        localStorage.setItem(DOC_PANEL_STORAGE_KEY, String(w));
        return w;
      });
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
  }, []);

  const handleDocEvent = useCallback((event: SSEEvent) => {
    const { type, data } = event;
    if (type === "doc_op_start") {
      const file = (data.file as string) || "unknown";
      setDocState({
        fileName: file.split("/").pop() || file,
        filePath: file,
        busy: true,
        previewHtml: null,
        previewLoading: false,
        previewError: null,
        events: [{ message: `📄 ${data.operation as string} ${file}`, timestamp: Date.now(), status: "running" }],
      });
      // Auto-switch to work mode when AI starts working on a document
      setMode("work");
    } else if (type === "doc_op_delta") {
      setDocState((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          busy: true,
          events: [...prev.events, { message: data.message as string, timestamp: Date.now(), status: "running" }],
        };
      });
      // Track element_path for highlight
      if (data.element_path) {
        setPendingHighlight({ path: data.element_path as string });
      }
    } else if (type === "doc_op_preview") {
      setDocState((prev) => {
        if (!prev) return prev;
        return { ...prev, previewHtml: (data.html as string) || prev.previewHtml, previewLoading: false };
      });
    } else if (type === "doc_op_done") {
      setDocState((prev) => {
        if (!prev) return prev;
        const ok = data.status === "ok";
        // If we have a pending highlight from delta, keep it for the new preview
        return {
          ...prev,
          busy: false,
          previewLoading: false,
          events: [
            ...prev.events,
            { message: (data.message as string) || (ok ? "✅ Complete" : "❌ Failed"), timestamp: Date.now(), status: ok ? "done" : "error" },
          ],
        };
      });
      // Refresh file tree to show new/modified files
      setFileTreeRefreshKey((k) => k + 1);
    }
  }, []);

  const wrappedOnEvent = useCallback((event: SSEEvent) => {
    if (event.type.startsWith("doc_op_")) {
      handleDocEvent(event);
    } else {
      handleTaskBoardEvent(event);
    }
  }, [handleTaskBoardEvent, handleDocEvent]);

  const {
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
    activeMonitors,
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
  } = useChatState(wrappedOnEvent, workspace, onAutoLoadSession);

  // ── Open Office document from file tree ───────────────────────
  const handleOpenDoc = useCallback(async (path: string, name: string) => {
    const ws = activeSession?.workspace || workspace || "";
    // HTML and Markdown files go directly to their workspace mode, no doc preview
    if (name.toLowerCase().endsWith(".html") || name.toLowerCase().endsWith(".md")) {
      setCurrentDocPath(path);
      setDocState(null);
      setMode("work");
      return;
    }
    setDocState({
      fileName: name,
      filePath: path,
      busy: true,
      previewHtml: null,
      previewLoading: true,
      previewError: null,
      events: [{ message: `📄 Opening ${name}…`, timestamp: Date.now(), status: "running" }],
      workspace: ws || undefined,
    });
    setCurrentDocPath(path);
    setMode("work");
    let installTimer: ReturnType<typeof setTimeout> | null = null;
    try {
      const preview = await documentsApi.getPreview(path, ws, (status) => {
        // Show install progress in preview error area
        const pct = status.progress || 0;
        const msg = status.message || "Installing...";
        const progressMsg = `⏳ 正在自动安装 OfficeCLI... ${pct}%\n${msg}`;
        setDocState((prev) => prev ? { ...prev, previewError: progressMsg, previewLoading: true } : prev);
      });
      if (installTimer) clearTimeout(installTimer);
      setDocState((prev) => prev ? {
        ...prev,
        busy: false,
        previewLoading: false,
        previewHtml: preview.html,
        previewError: null,
        events: [...prev.events, { message: `✅ Opened ${name}`, timestamp: Date.now(), status: "done" }],
      } : prev);
    } catch (e: any) {
      if (installTimer) clearTimeout(installTimer);
      // If it was an install failure, show a more helpful message
      const isInstallFail = e?.message?.includes("OfficeCLI");
      setDocState((prev) => prev ? {
        ...prev,
        busy: false,
        previewLoading: false,
        previewError: isInstallFail
          ? "❌ OfficeCLI 安装失败。请手动安装：\nwinget install HaiYing.OfficeCLI\n或访问 https://github.com/iOfficeAI/OfficeCLI/releases"
          : (e?.message || "Failed to open document"),
        events: [...prev.events, { message: `❌ Failed: ${e?.message || "Unknown error"}`, timestamp: Date.now(), status: "error" }],
      } : prev);
    }
  }, [activeSession?.workspace, workspace]);

  // Sync active session ID to parent (for NavBar language switcher reset)
  useEffect(() => {
    onActiveSessionChange?.(activeSession?.session_id || null);
  }, [activeSession?.session_id, onActiveSessionChange]);

  const [showProviders, setShowProviders] = useState(false);
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null);
  const [showMcpServers, setShowMcpServers] = useState(false);
  const [showTasks, setShowTasks] = useState(false);
  const [showEmail, setShowEmail] = useState(false);

  useEffect(() => {
    if (!selectedProvider && selectedModel && providerModels.length > 0) {
      for (const pm of providerModels) {
        if (pm.models.some((m) => m.id === selectedModel)) {
          setSelectedProvider(pm.provider.name);
          break;
        }
      }
    }
  }, [selectedModel, providerModels, selectedProvider]);
  const [showScheduledTasks, setShowScheduledTasks] = useState(false);
  const [showSkills, setShowSkills] = useState(false);
  const [viewingSubAgent, setViewingSubAgent] = useState<string | null>(null);
  const [showDelegate, setShowDelegate] = useState(false);
  const [showResultCompare, setShowResultCompare] = useState(false);
  const [showFiles, setShowFiles] = useState(false);
  const [showWorkFiles, setShowWorkFiles] = useState(false);
  const [pendingImages, setPendingImages] = useState<string[]>([]);
  const [pendingFiles, setPendingFiles] = useState<{ name: string; path: string; size: number }[]>([]);
  const [reasoningEffort, setReasoningEffort] = useState("medium");
  const [agentProfiles, setAgentProfiles] = useState<AgentProfileType[]>([]);
  const [agentOpen, setAgentOpen] = useState(false);
  const [effortOpen, setEffortOpen] = useState(false);
  const agentDropdownRef = useRef<HTMLDivElement>(null);
  const effortDropdownRef = useRef<HTMLDivElement>(null);
  const [selectedAgent, setSelectedAgent] = useState("default");
  const [localeMismatch, setLocaleMismatch] = useState<{ pendingText: string; pendingImages: string[]; pendingFiles: { name: string; path: string; size: number }[] } | null>(null);
  const [mcpServers, setMcpServers] = useState<McpServer[]>([]);
  const [mcpStatus, setMcpStatus] = useState<McpServerStatus[]>([]);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

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
        document.querySelector<HTMLTextAreaElement>('[placeholder="Type a message…"]')?.focus();
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

  // Click outside to close agent/effort dropdowns
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (agentOpen && agentDropdownRef.current && !agentDropdownRef.current.contains(e.target as Node)) {
        setAgentOpen(false);
      }
      if (effortOpen && effortDropdownRef.current && !effortDropdownRef.current.contains(e.target as Node)) {
        setEffortOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [agentOpen, effortOpen]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setAgentOpen(false);
        setEffortOpen(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const onSelectSession = useCallback(
    async (session: Session) => {
      const model = await selectSession(session, selectedModel, models);
      setSelectedModel(model);
      if (session.agent) {
        setSelectedAgent(session.agent);
      }
      if (session.provider) {
        setSelectedProvider(session.provider);
      } else if (model && providerModels.length > 0) {
        for (const pm of providerModels) {
          if (pm.models.some((m) => m.id === model)) {
            setSelectedProvider(pm.provider.name);
            break;
          }
        }
      }
      clearTaskBoard();
    },
    [selectSession, selectedModel, models, setSelectedModel, providerModels, clearTaskBoard],
  );

  const onNewSession = useCallback(async () => {
    const model = await newSession(selectedModel, models);
    setSelectedModel(model);
    setSelectedAgent("default");
    clearTaskBoard();
  }, [newSession, selectedModel, models, setSelectedModel, clearTaskBoard]);

  const onSelectSessionById = useCallback(
    async (sessionId: string) => {
      const model = await selectSessionById(sessionId, selectedModel, models);
      setSelectedModel(model);
    },
    [selectSessionById, selectedModel, models, setSelectedModel],
  );

  const _OFFICE_EXTS = [".docx", ".xlsx", ".pptx"];
  const _TEXT_EXTS = [".pdf", ".csv", ".txt", ".md", ".json", ".xml", ".html", ".htm", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".c", ".cpp", ".h", ".sh", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".sql", ".r", ".rb", ".php", ".css", ".scss", ".vue", ".svelte"];

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

  const processDocFile = async (file: File) => {
    const ext = "." + file.name.split(".").pop()?.toLowerCase();
    if (!_OFFICE_EXTS.includes(ext) && !_TEXT_EXTS.includes(ext)) return;

    try {
      const { uploadFile } = await import("../api/files");
      const result = await uploadFile(file);
      setPendingFiles((prev) => [
        ...prev,
        { name: file.name, path: result.path, size: result.size },
      ]);
    } catch (e) {
      console.error("File upload failed:", e);
    }
  };

  const processFile = (file: File) => {
    if (file.type.startsWith("image/")) {
      processImageFile(file);
    } else {
      processDocFile(file);
    }
  };

  const handleFilePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    let hasFile = false;
    for (const item of Array.from(items)) {
      if (item.kind === "file") {
        const file = item.getAsFile();
        if (file) {
          hasFile = true;
          processFile(file);
        }
      }
    }
    if (hasFile) e.preventDefault();
  };

  const handleFileUpload = () => {
    const el = document.createElement("input");
    el.type = "file";
    el.accept = "image/*,.docx,.xlsx,.pptx,.pdf,.csv,.txt,.md,.json,.xml,.html,.htm";
    el.multiple = true;
    el.onchange = (e) => {
      const files = (e.target as HTMLInputElement).files;
      if (files) Array.from(files).forEach(processFile);
    };
    el.click();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const files = e.dataTransfer?.files;
    if (files) Array.from(files).forEach(processFile);
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

  const doSend = async (text: string, images: string[], files: { name: string; path: string; size: number }[] = []) => {
    if (!activeSession || sending) return;

    // Append file references to the prompt text
    if (files.length > 0) {
      const fileList = files.map((f) => `- ${f.path} (${f.name}, ${(f.size / 1024).toFixed(0)}KB)`).join("\n");
      text = text + (text ? "\n\n" : "") + `📎 附件：\n${fileList}\n\n请先读取附件内容，然后根据我的请求处理。`;
    }

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
        text || "Please analyze this image",
        selectedModel,
        images.length > 0 ? images : undefined,
        selectedAgent,
        reasoningEffort,
        selectedProvider ?? undefined,
        currentDocPath || undefined,
        mode === "work" ? workspaceType : undefined,
        mode === "work",
      );
    } catch {
      setSending(false);
    }
  };

  const handleSend = async (text: string) => {
    if ((!text.trim() && pendingImages.length === 0 && pendingFiles.length === 0) || !activeSession || sending)
      return;

    // Check locale mismatch
    const currentLocale = i18n.language;
    if (activeSession.prompt_locale && activeSession.prompt_locale !== currentLocale) {
      setLocaleMismatch({ pendingText: text, pendingImages: [...pendingImages], pendingFiles: [...pendingFiles] });
      return;
    }

    const images = [...pendingImages];
    const files = [...pendingFiles];
    setPendingImages([]);
    setPendingFiles([]);
    doSend(text, images, files);
  };

  const handleSendWithLocale = async (text: string, images: string[], locale: string) => {
    // Reset cached system prompt then send
    try {
      const { api } = await import("../api/client");
      await api.post(`/sessions/${activeSession?.session_id}/reset-system-prompt`, {});
    } catch (e) {
      console.error("Failed to reset system prompt:", e);
    }
    if (activeSession) {
      setActiveSession({ ...activeSession, prompt_locale: locale });
    }
    doSend(text, images, localeMismatch?.pendingFiles ?? []);
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
      await sessionsApi.sendPrompt(activeSession.session_id, promptText, selectedModel, undefined, undefined, undefined, selectedProvider ?? undefined);
    } catch {
      setSending(false);
    }
  };

  const handleAgentBarClick = (agent: AgentProfileType) => {
    const textarea = document.querySelector<HTMLTextAreaElement>("textarea");
    if (!textarea) return;
    const mention = `@${agent.name} `;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const value = textarea.value;
    // Insert @agent at cursor position (or prepend if cursor is at start)
    const newValue = value.substring(0, start) + mention + value.substring(end);
    // Use React's internal setter to update state
    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, "value"
    )?.set;
    nativeInputValueSetter?.call(textarea, newValue);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    // Move cursor after the inserted mention
    const newPos = start + mention.length;
    textarea.setSelectionRange(newPos, newPos);
    textarea.focus();
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

  const quickActionPrompts: Record<string, string> = {
    digest: t("quickAction.digestPrompt"),
    remind: t("quickAction.remindPrompt"),
    inbox: t("quickAction.inboxPrompt"),
  };

  const handleQuickAction = useCallback(
    async (action: "digest" | "remind" | "inbox") => {
      const promptText = quickActionPrompts[action];
      if (!promptText) return;
      // Ensure we have an active session
      let sid = activeSession?.session_id;
      if (!sid) {
        const model = await newSession(selectedModel, models);
        setSelectedModel(model);
        sid = ""; // newSession sets activeSession via state; next render will have it
      }
      if (!activeSession && !sid) return;
      const targetSid = activeSession?.session_id || sid;
      if (!targetSid) return;
      setMessages((prev) => [
        ...prev,
        { id: `u-${Date.now()}`, role: "user", content: promptText },
      ]);
      setSending(true);
      try {
        await sessionsApi.sendPrompt(targetSid, promptText, selectedModel, undefined, undefined, undefined, selectedProvider ?? undefined);
      } catch {
        setSending(false);
      }
    },
    [activeSession, selectedModel, models, selectedProvider, newSession, setMessages, setSending, setSelectedModel, quickActionPrompts],
  );

  const handleNotificationAction = useCallback(
    (n: { title: string; body: string }) => {
      const textarea = document.querySelector<HTMLTextAreaElement>("textarea");
      if (textarea) {
        const text = `${t("notification.emailAction")}\n\n${n.body}`;
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
          window.HTMLTextAreaElement.prototype, "value"
        )?.set;
        nativeInputValueSetter?.call(textarea, text);
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
        textarea.focus();
      }
    },
    [],
  );

  // ── Workspace type detection ──────────────────────────────
  const CODE_EXTS = new Set(["py", "ts", "tsx", "js", "jsx", "json", "go", "rs", "java", "c", "cpp", "css", "scss", "vue", "svelte", "sh", "bash", "yaml", "yml", "toml", "sql"]);
  const detectWorkspaceType = (name: string): WorkspaceType => {
    const ext = name.split(".").pop()?.toLowerCase() || "";
    if (ext === "html") return "prototype";
    if (ext === "md") return "markdown";
    if (CODE_EXTS.has(ext)) return "code";
    return "document";
  };

  useEffect(() => {
    if (currentDocPath) {
      const type = detectWorkspaceType(currentDocPath);
      setWorkspaceType(type);
    }
  }, [currentDocPath]);

  const handleAIEdit = useCallback((instruction: string, selectedText: string) => {
    // Workspace context (file path, type) is already injected via workspace message.
    // Only need to send the selected text + instruction.
    if (!activeSession) return;
    const text = selectedText
      ? `修改这段内容（原文）：\n\n> ${selectedText}\n\n修改要求：${instruction}`
      : instruction;
    if (text.trim() && !sending) {
      setMessages((prev) => [...prev, { id: `u-${Date.now()}`, role: "user", content: text }]);
      setSending(true);
      sessionsApi.sendPrompt(
        activeSession.session_id, text, selectedModel, undefined, selectedAgent,
        reasoningEffort, selectedProvider ?? undefined,
        currentDocPath || undefined,
        mode === "work" ? workspaceType : undefined,
        mode === "work",
      )
        .catch(() => setSending(false));
    }
  }, [activeSession, selectedModel, selectedAgent, reasoningEffort, selectedProvider, currentDocPath, mode, workspaceType, sending, setMessages, setSending]);

  const completedTasks = taskBoardTasks.filter((t) => t.status === "done");

  return (
    <div className="relative flex h-full overflow-hidden bg-[var(--bg-primary)]">
      {/* ── Session List ── */}
      {mode === "chat" && (
        <SessionList
          sessions={sessions}
          activeId={activeSession?.session_id || null}
          onSelect={onSelectSession}
          onNew={onNewSession}
          onDelete={handleDeleteSession}
          onOpenProviders={() => setShowProviders(true)}
          onOpenMcpServers={() => setShowMcpServers(true)}
          onOpenTasks={() => setShowTasks(true)}
          onOpenEmail={() => setShowEmail(true)}
          onOpenScheduledTasks={() => setShowScheduledTasks(true)}
          onOpenSkills={() => setShowSkills(true)}
          onQuickAction={handleQuickAction}
          mobileOpen={mobileSidebarOpen}
          onMobileClose={() => setMobileSidebarOpen(false)}
          workspace={activeSession?.workspace || workspace || undefined}
          activeMonitors={activeMonitors}
        />
      )}
      {mode === "work" && (
        <div className="w-12 shrink-0 border-r border-[var(--border)] bg-[var(--bg-secondary)] flex flex-col items-center py-2 gap-2">
          <button
            onClick={() => setMode("chat")}
            className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-[var(--bg-tertiary)] text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
            title={t("session.sessions")}
          >
            <MessageSquare size={16} />
          </button>
        </div>
      )}

      {mode === "work" ? (
        /* ── WORK MODE ───────────────────────────────────────── */
        <>
          {/* AI Chat — left sidebar (350px) */}
          <div className="w-[350px] shrink-0 min-h-0 overflow-hidden border-r border-[var(--border)] bg-[var(--bg-primary)] flex flex-col">
            <div className="flex-1 min-h-0 flex flex-col">
              {activeSession ? (
                <>
                  {replaying && replayProgress.total > 0 && (
                    <div className="px-4 pt-2 pb-1 border-b border-[var(--border)] bg-[var(--bg-secondary)]">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs text-[var(--success)] flex items-center gap-1.5">
                          <Sparkles size={11} className="animate-pulse" />
                          {t("chat.replayingBranch")}
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
                    sessionId={activeSession.session_id}
                    messages={messages}
                    connected={connected}
                    sending={sending}
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
                    className="shrink-0 px-2 pt-1"
                    style={{ paddingBottom: "max(0.5rem, env(safe-area-inset-bottom))" }}
                    onDrop={handleDrop}
                    onDragOver={handleDragOver}
                  >
                    <AgentBar onAgentClick={handleAgentBarClick} />

                    {/* Agent + Model selectors */}
                    <div className="mb-1 flex items-center gap-2 flex-wrap">
                      {agentProfiles.length > 0 && (
                        <div ref={agentDropdownRef} className="flex items-center gap-1.5 relative">
                          <span className="text-[11px] text-[var(--text-tertiary)]">
                            Agent
                          </span>
                          <button
                            onClick={() => setAgentOpen((v) => !v)}
                            className="flex items-center gap-1.5 text-xs h-7 pl-2.5 pr-1.5 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--brand)] focus:ring-2 focus:ring-[var(--brand)]/30 transition-colors"
                          >
                            <span className="truncate max-w-[80px]">
                              {selectedAgent === "default"
                                ? "🦀 default"
                                : (() => {
                                    const p = agentProfiles.find((a) => a.name === selectedAgent);
                                    return `${p?.icon || "🤖"} ${p?.display_name || selectedAgent}`;
                                  })()}
                            </span>
                            <ChevronDown size={13} className={cn("text-[var(--text-tertiary)] transition-transform shrink-0", agentOpen && "rotate-180")} />
                          </button>
                          {agentOpen && (
                            <div className="absolute bottom-full mb-1.5 right-0 z-50 min-w-[160px] rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] shadow-[var(--shadow-lg)] py-1.5">
                              {[{ name: "default", icon: "🦀", display_name: "default" as const }, ...agentProfiles].map((a) => {
                                const isSelected = a.name === selectedAgent;
                                return (
                                  <button
                                    key={a.name}
                                    onClick={async () => {
                                      setSelectedAgent(a.name);
                                      setAgentOpen(false);
                                      if (activeSession) {
                                        try { await sessionsApi.switchAgent(activeSession.session_id, a.name); } catch {}
                                      }
                                    }}
                                    className={cn(
                                      "w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left transition-colors",
                                      isSelected ? "bg-[var(--brand-bg)] text-[var(--brand)]" : "text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
                                    )}
                                  >
                                    <span>{a.icon || "🤖"}</span>
                                    <span className="flex-1 truncate">{a.display_name}</span>
                                    {isSelected && <Check size={13} className="shrink-0 text-[var(--brand)]" />}
                                  </button>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      )}
                      {modelsLoading ? (
                        <div className="flex items-center gap-1.5">
                          <Loader2 size={12} className="animate-spin text-[var(--text-tertiary)]" />
                          <span className="text-[11px] text-[var(--text-tertiary)]">Loading…</span>
                        </div>
                      ) : providerModels.length > 0 ? (
                        <div className="flex items-center gap-1.5">
                          <span className="text-[11px] text-[var(--text-tertiary)]">
                            {t("chatPage.model")}
                          </span>
                          <ModelSelector
                            providerModels={providerModels}
                            selectedModel={selectedModel}
                            selectedProvider={selectedProvider}
                            onChange={(modelId, providerName) => {
                              setSelectedModel(modelId);
                              setSelectedProvider(providerName);
                            }}
                            disabled={modelsLoading}
                          />
                        </div>
                      ) : (
                        <div className="flex items-center gap-1.5">
                          <span className="text-[11px] text-[var(--text-tertiary)]">
                            {t("chatPage.model")}
                          </span>
                          <input
                            type="text"
                            value={selectedModel}
                            onChange={(e) => setSelectedModel(e.target.value)}
                            placeholder={t("chatPage.modelPlaceholder")}
                            className="text-xs h-7 px-2 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] font-mono focus:outline-none focus:border-[var(--brand)] focus:ring-2 focus:ring-[var(--brand)]/30 w-24 placeholder:text-[var(--text-tertiary)]"
                          />
                          {modelsError && (
                            <span
                              className="text-[10px] text-[var(--danger)] cursor-pointer"
                              title={modelsError}
                              onClick={() => window.location.reload()}
                            >
                              {t("chatPage.retry")}
                            </span>
                          )}
                        </div>
                      )}
                      <div ref={effortDropdownRef} className="flex items-center gap-1.5 relative">
                        <span className="text-[11px] text-[var(--text-tertiary)]">
                          {t("chatPage.effort")}
                        </span>
                        <button
                          onClick={() => setEffortOpen((v) => !v)}
                          className="flex items-center gap-1.5 text-xs h-7 pl-2.5 pr-1.5 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] font-mono focus:outline-none focus:border-[var(--brand)] focus:ring-2 focus:ring-[var(--brand)]/30 transition-colors"
                        >
                          <span>{t(`chatPage.reasoning${reasoningEffort.charAt(0).toUpperCase() + reasoningEffort.slice(1)}`)}</span>
                          <ChevronDown size={13} className={cn("text-[var(--text-tertiary)] transition-transform shrink-0", effortOpen && "rotate-180")} />
                        </button>
                        {effortOpen && (
                          <div className="absolute bottom-full mb-1.5 right-0 z-50 min-w-[120px] rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] shadow-[var(--shadow-lg)] py-1.5">
                            {["reasoningLow", "reasoningMedium", "reasoningHigh"].map((key) => {
                              const label = t(`chatPage.${key}`);
                              const effort = key.replace("reasoning", "").toLowerCase();
                              const isSelected = effort === reasoningEffort;
                              return (
                                <button
                                  key={effort}
                                  onClick={() => {
                                    setReasoningEffort(effort);
                                    setEffortOpen(false);
                                  }}
                                  className={cn(
                                    "w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left transition-colors",
                                    isSelected ? "bg-[var(--brand-bg)] text-[var(--brand)]" : "text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
                                  )}
                                >
                                  <span className="flex-1">{label}</span>
                                  {isSelected && <Check size={13} className="shrink-0 text-[var(--brand)]" />}
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </div>
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
                              aria-label={t("chatPage.removeImage")}
                            >
                              <X size={11} />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Pending files (documents, text, etc.) */}
                    {pendingFiles.length > 0 && (
                      <div className="flex gap-2 mb-2 flex-wrap">
                        {pendingFiles.map((f, i) => (
                          <div key={i} className="relative flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)] max-w-[200px]">
                            <FileText size={14} className="shrink-0 text-[var(--accent)]" />
                            <div className="min-w-0">
                              <div className="text-xs text-[var(--text-primary)] truncate">{f.name}</div>
                              <div className="text-[10px] text-[var(--text-tertiary)]">{(f.size / 1024).toFixed(0)}KB</div>
                            </div>
                            <button
                              onClick={() =>
                                setPendingFiles((prev) =>
                                  prev.filter((_, idx) => idx !== i),
                                )
                              }
                              className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full flex items-center justify-center bg-[var(--danger)] text-white hover:bg-[var(--danger-hover)] transition-colors"
                              aria-label="Remove file"
                            >
                              <X size={11} />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Input row */}
                    <div className="flex gap-1.5 items-end">
                      <ChatInput
                        sending={sending}
                        replaying={replaying}
                        onSend={handleSend}
                        onAbort={handleAbort}
                        onFileUpload={handleFileUpload}
                        onFilePaste={handleFilePaste}
                        onDelegateOpen={() => setShowDelegate(true)}
                        showDelegate={true}
                      />
                    </div>
                  </div>
                </>
              ) : (
                <div className="flex-1 flex items-center justify-center px-4">
                  <div className="text-center">
                    <div className="w-12 h-12 rounded-2xl mx-auto mb-3 flex items-center justify-center text-2xl"
                      style={{ background: "linear-gradient(135deg, var(--brand) 0%, var(--brand-active) 100%)" }}
                    >
                      🦀
                    </div>
                    <p className="text-xs text-[var(--text-tertiary)]">{t("chatPage.welcome")}</p>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Workspace — right side (flex-1) */}
          <div className="flex-1 flex flex-col min-w-0 bg-[var(--bg-primary)]">
            {/* Work mode toolbar */}
            <div className="flex items-center gap-2 px-3 h-11 border-b border-[var(--border)] bg-[var(--bg-secondary)] shrink-0">
              <button
                onClick={() => setMode("chat")}
                className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
              >
                <MessageSquare size={13} />
                {t("document.chatMode")}
              </button>
              <button
                onClick={onNewSession}
                className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
              >
                <Sparkles size={13} />
                {t("chat.startNewConversation")}
              </button>
              <button
                onClick={handleStartMeeting}
                className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-[var(--text-tertiary)] hover:text-[var(--accent)] hover:bg-[var(--accent-bg)] transition-colors"
              >
                📝 {t("chat.startMeeting")}
              </button>
              <div className="flex-1 min-w-0" />
              <WorkspaceSwitcher current={workspace} onChange={setWorkspace} />
              <Button
                size="icon"
                variant="ghost"
                onClick={() => setShowWorkFiles((v) => !v)}
                title={showWorkFiles ? t("fileTree.hide") : t("fileTree.show")}
                className={cn(showWorkFiles ? "text-[var(--brand)] bg-[var(--brand-bg)]" : "")}
              >
                {showWorkFiles ? <PanelRightClose size={15} /> : <PanelRightOpen size={15} />}
              </Button>
              {docState && (
                <>
                  <div className="w-px h-4 bg-[var(--border)]" />
                  <span className="text-sm font-medium truncate text-[var(--text-primary)]">
                    {docState.fileName}
                  </span>
                  <div className="flex-1" />
                  <button
                    onClick={() => { setDocState(null); setCurrentDocPath(null); setMeetingActive(false); }}
                    className="p-1 rounded text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
                  >
                    <X size={14} />
                  </button>
                </>
              )}
              {meetingActive && (
                <>
                  <div className="w-px h-4 bg-[var(--border)]" />
                  <span className="text-sm font-medium text-[var(--text-primary)]">
                    📝 {t("meeting.titlePlaceholder")}
                  </span>
                  <div className="flex-1" />
                </>
              )}
            </div>

            {/* Workspace content — horizontal: content + file list */}
            <div className="flex-1 min-h-0 flex">
              {/* Content area (left) */}
              <div className="flex-1 min-h-0 overflow-hidden">
                {meetingActive && activeSession ? (
                  <MeetingPanel
                    sessionId={activeSession.session_id}
                    onPrompt={(text) => {
                      setMessages((prev) => [...prev, { id: `u-${Date.now()}`, role: "user", content: text }]);
                      setSending(true);
                      sessionsApi.sendPrompt(activeSession.session_id, text, selectedModel, undefined, selectedAgent, reasoningEffort, selectedProvider ?? undefined, currentDocPath || undefined)
                        .catch(() => setSending(false));
                    }}
                  />
                ) : workspaceType === "code" && currentDocPath ? (
                  <CodePanel
                    key={currentDocPath}
                    initialPath={currentDocPath}
                    initialContent=""
                    workMode={true}
                  />
                ) : workspaceType === "prototype" && currentDocPath ? (
                  <PrototypePanel
                    key={currentDocPath}
                    filePath={currentDocPath}
                    onClose={() => { setDocState(null); setCurrentDocPath(null); }}
                  />
                ) : workspaceType === "markdown" && currentDocPath ? (
                  <MarkdownPanel
                    key={currentDocPath}
                    filePath={currentDocPath}
                    onClose={() => { setDocState(null); setCurrentDocPath(null); }}
                  />
                ) : docState ? (
                  <DocumentPanel
                    doc={docState}
                    onClose={() => { setDocState(null); setCurrentDocPath(null); }}
                    maximized={false}
                    onToggleMaximize={() => {}}
                    onDownload={() => {
                      if (docState?.filePath) {
                        const link = document.createElement("a");
                        link.href = `/api/documents/download?path=${encodeURIComponent(docState.filePath)}`;
                        link.download = docState.fileName;
                        link.click();
                      }
                    }}
                    onRefreshPreview={async () => {
                      if (!docState?.filePath) return;
                      setDocState((prev) => prev ? { ...prev, previewLoading: true } : prev);
                      try {
                        const preview = await documentsApi.getPreview(
                          docState.filePath,
                          docState.workspace || activeSession?.workspace || "",
                        );
                        setDocState((prev) => prev ? {
                          ...prev,
                          previewLoading: false,
                          previewHtml: preview.html,
                          previewError: null,
                        } : prev);
                      } catch (e: any) {
                        setDocState((prev) => prev ? {
                          ...prev,
                          previewLoading: false,
                          previewError: e?.message || "刷新预览失败",
                        } : prev);
                      }
                    }}
                    workMode={true}
                    pendingHighlight={pendingHighlight}
                    onAIEdit={handleAIEdit}
                  />
                ) : (
                  <div className="h-full flex items-center justify-center text-[var(--text-tertiary)]">
                    <div className="text-center">
                      <LayoutPanelTop size={32} className="mx-auto mb-3 opacity-30" />
                      <p className="text-sm">{t("document.workModeEmpty")}</p>
                    </div>
                  </div>
                )}
              </div>

              {/* File list in work mode — right side */}
              <FileBrowser
                collapsed={!showWorkFiles}
                onToggle={() => setShowWorkFiles((v) => !v)}
                sessionId={activeSession?.session_id || null}
                workspace={activeSession?.workspace || workspace || undefined}
                onOpenDoc={(path, name) => {
                  setShowWorkFiles(false);
                  handleOpenDoc(path, name);
                }}
                refreshTrigger={fileTreeRefreshKey}
              />
            </div>
          </div>
        </>
      ) : (
        <>
        <div className="flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden">
          {/* Toolbar */}
          <div className="flex items-center gap-1 px-3 h-11 shrink-0 border-b border-[var(--border)] bg-[var(--bg-secondary)]">
            <Button
              size="icon"
              variant="ghost"
              onClick={() => setMobileSidebarOpen(true)}
              title={t("session.sessions")}
              className="md:hidden"
            >
              <Menu size={16} />
            </Button>
            <WorkspaceSwitcher current={workspace} onChange={setWorkspace} />
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
            <NotificationBell onSwitchSession={onSelectSessionById} onNotificationAction={handleNotificationAction} />
            {completedTasks.length > 0 && (
              <Button
                size="icon"
                variant="ghost"
                onClick={() => setShowResultCompare(true)}
                title={t("taskBoard.title")}
                className="text-[var(--accent-2)] hover:text-[var(--accent-2)] hover:bg-[var(--accent-2-bg)]"
              >
                <Bot size={15} />
              </Button>
            )}
            <Button
              size="icon"
              variant="ghost"
              onClick={() => setShowFiles((v) => !v)}
              title={showFiles ? t("fileTree.hide") : t("fileTree.show")}
              className={cn(showFiles ? "text-[var(--brand)] bg-[var(--brand-bg)]" : "")}
            >
              {showFiles ? <PanelRightClose size={15} /> : <PanelRightOpen size={15} />}
            </Button>
            <Button
              size="icon"
              variant="ghost"
              onClick={() => setMode("work")}
              title={t("document.workMode")}
              className="text-[var(--text-tertiary)] hover:text-[var(--accent)] hover:bg-[var(--accent-bg)]"
            >
              <LayoutPanelLeft size={15} />
            </Button>
          </div>

        {activeSession ? (
          <>
            {replaying && replayProgress.total > 0 && (
              <div className="px-4 pt-2 pb-1 border-b border-[var(--border)] bg-[var(--bg-secondary)]">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-[var(--success)] flex items-center gap-1.5">
                    <Sparkles size={11} className="animate-pulse" />
                    {t("chat.replayingBranch")}
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
              sessionId={activeSession.session_id}
              messages={messages}
              connected={connected}
              sending={sending}
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
              className="shrink-0 px-2 sm:px-4 pt-1 sm:pt-2"
              style={{ paddingBottom: "max(0.5rem, env(safe-area-inset-bottom))" }}
              onDrop={handleDrop}
              onDragOver={handleDragOver}
            >
              <AgentBar onAgentClick={handleAgentBarClick} />

              {/* Agent + Model selectors */}
              <div className="mb-1 sm:mb-2 flex items-center gap-2 flex-wrap">
                {agentProfiles.length > 0 && (
                  <div ref={agentDropdownRef} className="flex items-center gap-1.5 relative">
                    <span className="text-[11px] text-[var(--text-tertiary)] hidden sm:inline">
                      Agent
                    </span>
                    <button
                      onClick={() => setAgentOpen((v) => !v)}
                      className="flex items-center gap-1.5 text-xs h-7 pl-2.5 pr-1.5 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--brand)] focus:ring-2 focus:ring-[var(--brand)]/30 transition-colors"
                    >
                      <span className="truncate max-w-[100px]">
                        {selectedAgent === "default"
                          ? "🦀 default"
                          : (() => {
                              const p = agentProfiles.find((a) => a.name === selectedAgent);
                              return `${p?.icon || "🤖"} ${p?.display_name || selectedAgent}`;
                            })()}
                      </span>
                      <ChevronDown size={13} className={cn("text-[var(--text-tertiary)] transition-transform shrink-0", agentOpen && "rotate-180")} />
                    </button>
                    {agentOpen && (
                      <div className="absolute bottom-full mb-1.5 right-0 z-50 min-w-[160px] rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] shadow-[var(--shadow-lg)] py-1.5">
                        {[{ name: "default", icon: "🦀", display_name: "default" as const }, ...agentProfiles].map((a) => {
                          const isSelected = a.name === selectedAgent;
                          return (
                            <button
                              key={a.name}
                              onClick={async () => {
                                setSelectedAgent(a.name);
                                setAgentOpen(false);
                                if (activeSession) {
                                  try { await sessionsApi.switchAgent(activeSession.session_id, a.name); } catch {}
                                }
                              }}
                              className={cn(
                                "w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left transition-colors",
                                isSelected ? "bg-[var(--brand-bg)] text-[var(--brand)]" : "text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
                              )}
                            >
                              <span>{a.icon || "🤖"}</span>
                              <span className="flex-1 truncate">{a.display_name}</span>
                              {isSelected && <Check size={13} className="shrink-0 text-[var(--brand)]" />}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
                {modelsLoading ? (
                  <div className="flex items-center gap-1.5">
                    <Loader2 size={12} className="animate-spin text-[var(--text-tertiary)]" />
                    <span className="text-[11px] text-[var(--text-tertiary)]">Loading models…</span>
                  </div>
                ) : providerModels.length > 0 ? (
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] text-[var(--text-tertiary)] hidden sm:inline">
                      {t("chatPage.model")}
                    </span>
                    <ModelSelector
                      providerModels={providerModels}
                      selectedModel={selectedModel}
                      selectedProvider={selectedProvider}
                      onChange={(modelId, providerName) => {
                        setSelectedModel(modelId);
                        setSelectedProvider(providerName);
                      }}
                      disabled={modelsLoading}
                    />
                  </div>
                ) : (
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] text-[var(--text-tertiary)] hidden sm:inline">
                      {t("chatPage.model")}
                    </span>
                    <input
                      type="text"
                      value={selectedModel}
                      onChange={(e) => setSelectedModel(e.target.value)}
                      placeholder={t("chatPage.modelPlaceholder")}
                      className="text-xs h-7 px-2 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] font-mono focus:outline-none focus:border-[var(--brand)] focus:ring-2 focus:ring-[var(--brand)]/30 w-28 sm:w-40 placeholder:text-[var(--text-tertiary)]"
                    />
                    {modelsError && (
                      <span
                        className="text-[10px] text-[var(--danger)] cursor-pointer"
                        title={modelsError}
                        onClick={() => window.location.reload()}
                      >
                        {t("chatPage.retry")}
                      </span>
                    )}
                  </div>
                )}
                <div ref={effortDropdownRef} className="flex items-center gap-1.5 relative">
                  <span className="text-[11px] text-[var(--text-tertiary)] hidden sm:inline">
                    {t("chatPage.effort")}
                  </span>
                  <button
                    onClick={() => setEffortOpen((v) => !v)}
                    className="flex items-center gap-1.5 text-xs h-7 pl-2.5 pr-1.5 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] font-mono focus:outline-none focus:border-[var(--brand)] focus:ring-2 focus:ring-[var(--brand)]/30 transition-colors"
                  >
                    <span>{t(`chatPage.reasoning${reasoningEffort.charAt(0).toUpperCase() + reasoningEffort.slice(1)}`)}</span>
                    <ChevronDown size={13} className={cn("text-[var(--text-tertiary)] transition-transform shrink-0", effortOpen && "rotate-180")} />
                  </button>
                  {effortOpen && (
                    <div className="absolute bottom-full mb-1.5 right-0 z-50 min-w-[120px] rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] shadow-[var(--shadow-lg)] py-1.5">
                      {["reasoningLow", "reasoningMedium", "reasoningHigh"].map((key) => {
                        const label = t(`chatPage.${key}`);
                        const effort = key.replace("reasoning", "").toLowerCase();
                        const isSelected = effort === reasoningEffort;
                        return (
                          <button
                            key={effort}
                            onClick={() => {
                              setReasoningEffort(effort);
                              setEffortOpen(false);
                            }}
                            className={cn(
                              "w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left transition-colors",
                              isSelected ? "bg-[var(--brand-bg)] text-[var(--brand)]" : "text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
                            )}
                          >
                            <span className="flex-1">{label}</span>
                            {isSelected && <Check size={13} className="shrink-0 text-[var(--brand)]" />}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
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
                        aria-label={t("chatPage.removeImage")}
                      >
                        <X size={11} />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* Pending files (documents, text, etc.) */}
              {pendingFiles.length > 0 && (
                <div className="flex gap-2 mb-2 flex-wrap">
                  {pendingFiles.map((f, i) => (
                    <div key={i} className="relative flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)] max-w-[200px]">
                      <FileText size={14} className="shrink-0 text-[var(--accent)]" />
                      <div className="min-w-0">
                        <div className="text-xs text-[var(--text-primary)] truncate">{f.name}</div>
                        <div className="text-[10px] text-[var(--text-tertiary)]">{(f.size / 1024).toFixed(0)}KB</div>
                      </div>
                      <button
                        onClick={() =>
                          setPendingFiles((prev) =>
                            prev.filter((_, idx) => idx !== i),
                          )
                        }
                        className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full flex items-center justify-center bg-[var(--danger)] text-white hover:bg-[var(--danger-hover)] transition-colors"
                        aria-label="Remove file"
                      >
                        <X size={11} />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* Input row */}
              <div className="flex gap-1.5 sm:gap-2 items-end">
                <ChatInput
                  sending={sending}
                  replaying={replaying}
                  onSend={handleSend}
                  onAbort={handleAbort}
                  onFileUpload={handleFileUpload}
                  onFilePaste={handleFilePaste}
                  onDelegateOpen={() => setShowDelegate(true)}
                  showDelegate={true}
                />
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
                {t("chatPage.welcome")}
              </h2>
              <p className="text-sm text-[var(--text-tertiary)] mb-6">
                {t("chat.welcomeSubtitle")}
              </p>
              <div className="grid grid-cols-2 gap-2 mb-6">
                {STARTER_PROMPTS.map((p, i) => (
                  <button
                    key={i}
                    onClick={() => {
                      onNewSession();
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
                      {t(p.labelKey)}
                    </span>
                  </button>
                ))}
              </div>
              <Button variant="brand" onClick={onNewSession}>
                <Sparkles size={14} /> {t("chat.startNewConversation")}
              </Button>
            </div>
          </div>
        )}
        </div>

        <FileBrowser
        collapsed={!showFiles}
        onToggle={() => setShowFiles((v) => !v)}
        sessionId={activeSession?.session_id || null}
        workspace={activeSession?.workspace || workspace || undefined}
        onOpenDoc={handleOpenDoc}
        refreshTrigger={fileTreeRefreshKey}
      />

      {/* Document Panel — right sidebar when AI is working on a doc */}
      {docState && (
        <div
          className={cn(
            "flex flex-col bg-[var(--bg-primary)] shrink-0 transition-[width] duration-150",
            docPanelMaximized
              ? "absolute inset-y-0 right-0 z-30 border-l-0 shadow-[-8px_0_24px_rgba(0,0,0,0.35)]"
              : "relative border-l border-[var(--border)]",
          )}
          style={
            docPanelMaximized
              ? { width: `calc(100% - ${SESSION_LIST_W}px)` }
              : { width: docPanelWidth, maxWidth: `calc(100% - ${SESSION_LIST_W}px - ${CHAT_MIN_W}px)` }
          }
        >
          {/* Drag handle for resizing — only in sidebar mode */}
          {!docPanelMaximized && (
            <div
              className="absolute left-0 inset-y-0 w-3 z-10 cursor-col-resize select-none
                         hover:w-4 transition-all group"
              onMouseDown={handleDocPanelResizeStart}
            >
              {/* Visible drag rail */}
              <div className="absolute inset-y-0 left-0 w-[3px]
                              bg-[var(--border-strong)] group-hover:bg-[var(--accent)]
                              group-active:bg-[var(--accent)] transition-colors" />
              {/* Grip dots — appear on hover */}
              <div className="flex flex-col items-center justify-center h-full gap-[3px] pl-[2px]
                              opacity-0 group-hover:opacity-100 transition-opacity">
                <div className="w-[4px] h-[4px] rounded-full bg-[var(--accent)]" />
                <div className="w-[4px] h-[4px] rounded-full bg-[var(--accent)]" />
                <div className="w-[4px] h-[4px] rounded-full bg-[var(--accent)]" />
              </div>
            </div>
          )}
          <DocumentPanel
            doc={docState}
            onClose={() => { setDocState(null); setCurrentDocPath(null); }}
            maximized={docPanelMaximized}
            onToggleMaximize={() => setDocPanelMaximized((v) => !v)}
            onDownload={() => {
              // Trigger download via backend
              if (docState?.filePath) {
                const link = document.createElement("a");
                link.href = `/api/documents/download?path=${encodeURIComponent(docState.filePath)}`;
                link.download = docState.fileName;
                link.click();
              }
            }}
            onRefreshPreview={async () => {
              if (!docState?.filePath) return;
              setDocState((prev) => prev ? { ...prev, previewLoading: true } : prev);
              try {
                const preview = await documentsApi.getPreview(
                  docState.filePath,
                  docState.workspace || activeSession?.workspace || "",
                );
                setDocState((prev) => prev ? {
                  ...prev,
                  previewLoading: false,
                  previewHtml: preview.html,
                  previewError: null,
                } : prev);
              } catch (e: any) {
                setDocState((prev) => prev ? {
                  ...prev,
                  previewLoading: false,
                  previewError: e?.message || "刷新预览失败",
                } : prev);
              }
            }}
          />
        </div>
      )}
        </>
      )}

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
          title={t("chatPage.welcome")}
          description={t("provider.addProvider")}
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
            refreshProviders();
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

      {showTasks && (
        <TaskPanel
          onClose={() => setShowTasks(false)}
          onSwitchSession={onSelectSessionById}
        />
      )}

      {showEmail && (
        <EmailPanel
          onClose={() => setShowEmail(false)}
        />
      )}

      {showSkills && <SkillsPanel onClose={() => setShowSkills(false)} />}

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

      {localeMismatch && (
        <Modal
          open={true}
          onOpenChange={(o) => !o && setLocaleMismatch(null)}
          title={t("localeMismatch.title")}
          description={t("localeMismatch.desc")}
          size="sm"
          footer={
            <div className="flex gap-2">
              <Button
                variant="brand"
                onClick={async () => {
                  const { pendingText, pendingImages: imgs } = localeMismatch;
                  setLocaleMismatch(null);
                  await handleSendWithLocale(pendingText, imgs, i18n.language);
                }}
              >
                {t("localeMismatch.rebuild")}
              </Button>
              <Button
                variant="ghost"
                onClick={async () => {
                  const { pendingText } = localeMismatch;
                  setLocaleMismatch(null);
                  setPendingImages([]);
                  setPendingFiles([]);
                  doSend(pendingText, [], []);
                }}
              >
                {t("localeMismatch.keep")}
              </Button>
              <Button variant="ghost" onClick={() => setLocaleMismatch(null)}>
                {t("common.cancel")}
              </Button>
            </div>
          }
        >
          <div className="text-sm text-[var(--text-secondary)] space-y-2">
            <p>{t("localeMismatch.current", { locale: i18n.language })}</p>
            <p>{t("localeMismatch.stored", { locale: activeSession?.prompt_locale || "en" })}</p>
          </div>
        </Modal>
      )}
    </div>
  );
}

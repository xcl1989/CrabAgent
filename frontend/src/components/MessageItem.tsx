/**
 * MessageItem — Extracted, memoized message rendering for ChatPanel.
 *
 * Each message type is rendered by a dedicated React.memo component so that
 * streaming token updates (which only change the last assistant message)
 * do not trigger re-renders of all other messages in the conversation.
 *
 * This is the single most impactful optimization for scroll performance:
 * without memo, every text_delta SSE event re-renders the ENTIRE message
 * list, blocking the main thread and preventing requestAnimationFrame
 * (and thus scrollToBottom) from running smoothly.
 */
import { memo, useState, useEffect, useRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  Terminal,
  FileText,
  Pencil,
  Search,
  Sparkles,
  Plug,
  Zap,
  Check,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  MessageSquare,
  Loader2,
  Wrench,
  X,
  GitBranch,
} from "lucide-react";
import { RichMarkdown } from "./rich-content/RichMarkdown";
import ToolResultRender from "./ToolResultRender";
import { SubAgentCard } from "./SubAgentCard";
import { cn } from "../lib/cn";

// ── Shared types ──────────────────────────────────────────────

export interface ChatMessage {
  id: string;
  role: string;
  content: string;
  reasoning_content?: string;
  tool_calls?: unknown[];
  isStreaming?: boolean;
  stats?: { elapsed: number; model: string; tokens: number; iterations: number };
  confirm_id?: string;
  tool_name?: string;
  tool_call_id?: string;
  args_summary?: string;
  confirmed?: boolean;
  options?: string[];
  source?: "builtin" | "mcp";
  server_name?: string;
  images?: string[];
  lazy_images?: boolean;
  sub_agent_id?: string;
  sub_agent_name?: string;
  sub_agent_display?: string;
  sub_agent_elapsed?: number;
  sub_agent_tokens?: number;
  sub_agent_iterations?: number;
  sub_agent_task?: string;
  sub_agent_model?: string;
  sub_agent_pipeline_run_id?: number | null;
  sub_agent_pipeline_step_id?: string | null;
  retry_info?: {
    phase: "retrying" | "countdown" | "exhausted";
    message: string;
    attempt: number;
    max_attempts: number;
    remaining_seconds?: number;
    delay_seconds?: number;
  };
  bashStream?: string;
  db_message_id?: number;
}

// ── Shared helpers ────────────────────────────────────────────

function getToolSummary(content: string): { name: string; summary: string } {
  try {
    const data = JSON.parse(content);
    const name = data.name || "unknown";
    const args = data.arguments || {};
    const firstKey = Object.keys(args)[0];
    let summary = "";
    if (firstKey) {
      const val = args[firstKey];
      summary =
        typeof val === "string"
          ? val.slice(0, 80)
          : JSON.stringify(val).slice(0, 80);
    }
    return { name, summary };
  } catch {
    return { name: "unknown", summary: content.slice(0, 80) };
  }
}

const TOOL_ICONS: Record<string, ReactNode> = {
  bash: <Terminal size={13} />,
  read: <FileText size={13} />,
  write: <Pencil size={13} />,
  edit: <Wrench size={13} />,
  glob: <Search size={13} />,
  grep: <Search size={13} />,
  skill: <Sparkles size={13} />,
};

function getToolIcon(name: string, isMcp: boolean): ReactNode {
  if (isMcp) return <Plug size={13} />;
  return TOOL_ICONS[name] || <Zap size={13} />;
}

// ── Callbacks type ────────────────────────────────────────────

interface MessageCallbacks {
  onPreviewImage?: (url: string) => void;
  onToolConfirm?: (confirmId: string, approved: boolean) => void;
  onUserInput?: (inputId: string, answer: string) => void;
  onBranch?: (messageId: string) => void;
  onToggle?: () => void;
}

// ── Individual memoized message components ────────────────────

/** Tool call + result pair (grouped) */
const ToolCallPairItem = memo(function ToolCallPairItem({
  callMsg,
  resultMsg,
  onPreviewImage,
  onToggle,
}: {
  callMsg: ChatMessage;
  resultMsg: ChatMessage;
  onPreviewImage?: (url: string) => void;
  onToggle?: () => void;
}) {
  const { name, summary } = getToolSummary(callMsg.content);
  const isMcp = callMsg.source === "mcp";
  const displayName = isMcp
    ? name.replace(/^mcp__/, "").replace(/__/g, ": ")
    : name;
  const accentVar = isMcp ? "var(--accent-2)" : "var(--accent)";

  return (
    <details
      className="mb-3 group ml-3 rounded-lg overflow-hidden"
      onToggle={(e) => { if (e.currentTarget.open) onToggle?.(); }}
    >
      <summary
        className={cn(
          "flex items-center gap-2 cursor-pointer py-1.5 px-3 text-xs select-none",
          "bg-[var(--bg-secondary)] border border-[var(--border)] rounded-lg",
          "hover:border-[var(--border-strong)] transition-colors",
          "list-none",
        )}
      >
        <span
          className="flex items-center justify-center w-5 h-5 rounded shrink-0"
          style={{ color: accentVar, background: isMcp ? "var(--accent-2-bg)" : "var(--accent-bg)" }}
        >
          {getToolIcon(name, isMcp)}
        </span>
        <span className="font-medium truncate" style={{ color: accentVar }}>
          {displayName}
        </span>
        {callMsg.server_name && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--accent-2-bg)] text-[var(--accent-2)] shrink-0">
            MCP · {callMsg.server_name}
          </span>
        )}
        {summary && (
          <span className="text-[var(--text-tertiary)] font-mono text-[11px] truncate">
            {summary}
          </span>
        )}
      </summary>

      <ToolResultRender
        name={name}
        argsJson={callMsg.content}
        result={resultMsg.content}
        images={resultMsg.images}
        onPreviewImage={onPreviewImage}
        accentVar={accentVar}
      />
    </details>
  );
});

/** Standalone tool_call (no matched result yet — streaming) */
const ToolCallItem = memo(function ToolCallItem({
  msg,
  onToggle,
}: {
  msg: ChatMessage;
  onToggle?: () => void;
}) {
  const { name, summary } = getToolSummary(msg.content);
  const isMcp = msg.source === "mcp";
  const displayName = isMcp
    ? name.replace(/^mcp__/, "").replace(/__/g, ": ")
    : name;
  const accentVar = isMcp ? "var(--accent-2)" : "var(--accent)";
  const bashStream = msg.bashStream;
  const isBashStreaming = name === "bash" && bashStream;

  return (
    <details
      className="mb-3 ml-3 rounded-lg overflow-hidden"
      open={isBashStreaming ? true : undefined}
    >
      <summary className="flex items-center gap-2 cursor-pointer py-1.5 px-3 text-xs select-none list-none bg-[var(--bg-secondary)] border border-[var(--border)] rounded-lg hover:border-[var(--border-strong)] transition-colors">
        <span
          className="flex items-center justify-center w-5 h-5 rounded shrink-0"
          style={{ color: accentVar, background: isMcp ? "var(--accent-2-bg)" : "var(--accent-bg)" }}
        >
          {getToolIcon(name, isMcp)}
        </span>
        <span className="font-medium truncate" style={{ color: accentVar }}>
          {displayName}
        </span>
        {msg.server_name && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--accent-2-bg)] text-[var(--accent-2)] shrink-0">
            MCP · {msg.server_name}
          </span>
        )}
        {summary && (
          <span className="text-[var(--text-tertiary)] font-mono text-[11px] truncate">
            {summary}
          </span>
        )}
        {isBashStreaming && (
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse shrink-0" />
        )}
      </summary>
      {isBashStreaming && (
        <div className="mt-1 p-2 rounded-b-lg bg-[#1e1e1e] border border-t-0 border-[var(--border)]">
          <pre className="whitespace-pre-wrap font-mono text-[11px] text-green-300 leading-relaxed m-0 max-h-64 overflow-y-auto">
            {bashStream}
          </pre>
        </div>
      )}
    </details>
  );
});

/** Thinking / reasoning block */
const ThinkingItem = memo(function ThinkingItem({
  msg,
  onToggle,
}: {
  msg: ChatMessage;
  onToggle?: () => void;
}) {
  const { t } = useTranslation();
  return (
    <details
      className="mb-3 ml-3 rounded-lg overflow-hidden"
      onToggle={(e) => { if (e.currentTarget.open) onToggle?.(); }}
    >
      <summary className="cursor-pointer py-1.5 px-3 text-xs rounded-lg select-none list-none bg-[var(--bg-secondary)] border border-[var(--border)] hover:border-[var(--border-strong)] transition-colors text-[var(--text-secondary)] flex items-center gap-2">
        <span className="text-[var(--accent-2)]">💭</span>
        <span>{t("chatPanel.thinking")}</span>
      </summary>
      <div className="mt-1.5 p-3 rounded-lg text-xs leading-relaxed bg-[var(--bg-secondary)] border border-[var(--border)] border-l-[3px] border-l-[var(--accent-2)]">
        <pre className="whitespace-pre-wrap font-mono text-[12px] text-[var(--text-secondary)] m-0 bg-transparent! p-0! border-0!">
          {msg.content}
        </pre>
      </div>
    </details>
  );
});

/** Context compression card */
const CompressItem = memo(function CompressItem({ msg }: { msg: ChatMessage }) {
  const { t } = useTranslation();
  return (
    <div className="mb-3 flex justify-center">
      <div className="w-full max-w-2xl rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)] overflow-hidden text-xs">
        <div className="flex items-center gap-1.5 px-3 py-1.5 text-[var(--text-tertiary)]">
          {msg.isStreaming ? (
            <Loader2 size={11} className="animate-spin" />
          ) : (
            <CheckCircle2 size={11} />
          )}
          <span>{t("chat.contextCompression", "上下文压缩")}</span>
        </div>
        {msg.content && (
          <div className="px-3 pb-2 pt-1 text-[var(--text-secondary)] whitespace-pre-wrap leading-relaxed opacity-80">
            {msg.content}
          </div>
        )}
      </div>
    </div>
  );
});

/** Notice / info pill */
const NoticeItem = memo(function NoticeItem({ msg }: { msg: ChatMessage }) {
  return (
    <div className="mb-3 ml-3">
      <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs bg-[var(--warning-bg)] border border-[var(--warning-border)] text-[var(--warning)]">
        <AlertTriangle size={12} />
        {msg.content}
      </div>
    </div>
  );
});

/** Tool confirmation request */
const ToolConfirmItem = memo(function ToolConfirmItem({
  msg,
  onToolConfirm,
}: {
  msg: ChatMessage;
  onToolConfirm?: (confirmId: string, approved: boolean) => void;
}) {
  const { t } = useTranslation();
  if (!msg.confirm_id) return null;
  const resolved = msg.confirmed !== undefined;
  return (
    <div className="mb-3 ml-3">
      <div
        className={cn(
          "px-4 py-3 rounded-xl text-sm bg-[var(--bg-secondary)] border border-[var(--border)]",
        )}
        style={{
          borderLeft: resolved
            ? `3px solid ${msg.confirmed ? "var(--success)" : "var(--danger)"}`
            : "3px solid var(--warning)",
        }}
      >
        <div className="flex items-center gap-2 mb-1.5">
          <AlertTriangle size={14} className="text-[var(--warning)]" />
          <span className="font-medium text-[var(--text-primary)]">
            {t("chatPanel.toolRequiresPermission", { tool: msg.tool_name || t("toolResult.tool") })}
          </span>
          {resolved && (
            <span
              className={cn(
                "text-xs flex items-center gap-1",
                msg.confirmed ? "text-[var(--success)]" : "text-[var(--danger)]",
              )}
            >
              {msg.confirmed ? (
                <><Check size={12} /> Allowed</>
              ) : (
                <><X size={12} /> Denied</>
              )}
            </span>
          )}
        </div>
        {msg.args_summary && (
          <pre className="text-[11px] mb-2 whitespace-pre-wrap break-all font-mono text-[var(--text-secondary)] m-0 bg-transparent! p-0! border-0!">
            {msg.args_summary}
          </pre>
        )}
        {!resolved && onToolConfirm && (
          <div className="flex gap-2 mt-2">
            <button
              onClick={() => onToolConfirm(msg.confirm_id!, true)}
              className="px-3 py-1.5 rounded-md text-xs font-medium bg-[var(--success-bg)] text-[var(--success)] border border-[var(--success-border)] hover:bg-[var(--success)] hover:text-white transition-colors flex items-center gap-1"
            >
              <Check size={12} /> Allow
            </button>
            <button
              onClick={() => onToolConfirm(msg.confirm_id!, false)}
              className="px-3 py-1.5 rounded-md text-xs font-medium bg-[var(--danger-bg)] text-[var(--danger)] border border-[var(--danger-border)] hover:bg-[var(--danger)] hover:text-white transition-colors flex items-center gap-1"
            >
              <X size={12} /> Deny
            </button>
          </div>
        )}
      </div>
    </div>
  );
});

/** User input request */
const UserInputItem = memo(function UserInputItem({
  msg,
  onUserInput,
}: {
  msg: ChatMessage;
  onUserInput?: (inputId: string, answer: string) => void;
}) {
  if (!msg.confirm_id) return null;
  const resolved = msg.confirmed !== undefined;
  const options = msg.options;
  return (
    <div className="mb-3 ml-3">
      <div
        className="px-4 py-3 rounded-xl text-sm bg-[var(--bg-secondary)] border border-[var(--border)]"
        style={{
          borderLeft: resolved
            ? "3px solid var(--success)"
            : "3px solid var(--accent)",
        }}
      >
        <div className="flex items-center gap-2 mb-1.5">
          <MessageSquare size={14} className="text-[var(--accent)]" />
          <span className="font-medium text-[var(--text-primary)]">
            {msg.content}
          </span>
        </div>
        {!resolved && onUserInput && options && options.length > 0 && (
          <UserInputOptions options={options} inputId={msg.confirm_id} onSubmit={onUserInput} />
        )}
        {!resolved && onUserInput && (!options || options.length === 0) && (
          <UserInputField inputId={msg.confirm_id} onSubmit={onUserInput} />
        )}
        {resolved && (
          <div className="text-xs mt-1 text-[var(--text-secondary)]">
            → {msg.content}
          </div>
        )}
      </div>
    </div>
  );
});

/** Error message */
const ErrorItem = memo(function ErrorItem({ msg }: { msg: ChatMessage }) {
  return (
    <div className="mb-3">
      <div className="flex items-start gap-2 px-4 py-3 rounded-xl text-sm bg-[var(--danger-bg)] border border-[var(--danger-border)] text-[var(--danger)]">
        <AlertTriangle size={14} className="mt-0.5 shrink-0" />
        <div className="whitespace-pre-wrap break-words">{msg.content}</div>
      </div>
    </div>
  );
});

/** Retry indicator */
const RetryItem = memo(function RetryItem({ msg }: { msg: ChatMessage }) {
  if (!msg.retry_info) return null;
  const ri = msg.retry_info;
  const isCountdown = ri.phase === "countdown";
  const remaining = ri.remaining_seconds ?? 0;
  const totalDelay = ri.delay_seconds ?? 0;
  const progress = totalDelay > 0 ? ((totalDelay - remaining) / totalDelay) * 100 : 0;

  return (
    <div className="mb-3">
      <div className="flex items-center gap-3 px-4 py-3 rounded-xl text-sm bg-[var(--warning-bg,rgba(245,158,11,0.08))] border border-[var(--warning-border,rgba(245,158,11,0.2))] text-[var(--warning-text,#f59e0b)]">
        <Loader2 size={14} className="shrink-0 animate-spin" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium">{ri.message}</span>
            {!isCountdown && ri.delay_seconds ? (
              <span className="text-xs opacity-80">
                {ri.delay_seconds.toFixed(0)}秒后重试（第{ri.attempt}/{ri.max_attempts}次）
              </span>
            ) : null}
            {isCountdown ? (
              <span className="text-xs opacity-80">
                {remaining}秒后重试（第{ri.attempt}/{ri.max_attempts}次）
              </span>
            ) : null}
          </div>
          {totalDelay > 0 ? (
            <div className="mt-1.5 h-1 rounded-full bg-[var(--border)] overflow-hidden">
              <div
                className="h-full rounded-full bg-[var(--warning-text,#f59e0b)] transition-all duration-1000 ease-linear"
                style={{ width: `${progress}%` }}
              />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
});

/** Screenshot */
const ScreenshotItem = memo(function ScreenshotItem({
  msg,
  onPreviewImage,
}: {
  msg: ChatMessage;
  onPreviewImage?: (url: string) => void;
}) {
  return (
    <div className="mb-3 ml-3 flex flex-wrap gap-2">
      {msg.lazy_images && (
        <div className="w-[1024px] max-w-full h-[400px] rounded-lg border border-[var(--border)] flex items-center justify-center text-xs text-[var(--text-secondary)] animate-pulse">
          <div className="flex items-center gap-2">
            <Loader2 size={14} className="animate-spin" />
            <span>Loading image…</span>
          </div>
        </div>
      )}
      {msg.images?.map((img, idx) => (
        <img
          key={idx}
          src={img}
          alt="Generated image"
          className="max-w-full max-h-[400px] rounded-lg object-contain cursor-pointer border border-[var(--border)] hover:border-[var(--brand-border)] transition-colors"
          onClick={() => onPreviewImage?.(img)}
          onError={(e) => { e.currentTarget.style.display = "none"; }}
        />
      ))}
    </div>
  );
});

/** User message — memoized so streaming tokens on assistant messages
 *  don't needlessly re-render past user bubbles. */
const UserMessageItem = memo(function UserMessageItem({
  msg,
  onPreviewImage,
  onBranch,
  replaying,
}: {
  msg: ChatMessage;
  onPreviewImage?: (url: string) => void;
  onBranch?: (messageId: string) => void;
  replaying?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="mb-4 group/msg relative flex justify-end">
      <div className="chat-bubble-user relative">
        {msg.lazy_images && (
          <div className="w-[200px] h-[200px] rounded-lg border border-[var(--border)] flex items-center justify-center text-xs text-[var(--text-secondary)] animate-pulse mb-2">
            <div className="flex items-center gap-1.5">
              <Loader2 size={12} className="animate-spin" />
              <span>Loading image…</span>
            </div>
          </div>
        )}
        {msg.images && msg.images.length > 0 && (
          <div className="flex gap-2 mb-2 flex-wrap">
            {msg.images.map((img, idx) => (
              <img
                key={idx}
                src={img}
                className="max-w-[200px] max-h-[200px] rounded-lg cursor-pointer object-contain"
                onClick={() => onPreviewImage?.(img)}
                alt=""
              />
            ))}
          </div>
        )}
        <p className="whitespace-pre-wrap leading-relaxed text-[14px]">
          {msg.content}
        </p>
        {onBranch && !replaying && !msg.isStreaming && msg.id.startsWith("db-") && (
          <button
            onClick={() => onBranch(msg.id)}
            title={t("chatPanel.branchFromHere")}
            className={cn(
              "absolute top-0 right-full mr-1.5",
              "opacity-0 group-hover/msg:opacity-100 transition-opacity",
              "text-xs px-2 py-1 rounded-md flex items-center gap-1",
              "bg-[var(--bg-secondary)] border border-[var(--border)] text-[var(--text-secondary)]",
              "hover:text-[var(--text-primary)] hover:border-[var(--border-strong)]",
            )}
          >
            <GitBranch size={11} />
            Branch
          </button>
        )}
      </div>
    </div>
  );
});

/** Assistant message — the most performance-critical component because
 *  its content changes on every streaming token. Memoized so that when
 *  the LAST assistant message is streaming, all PREVIOUS messages are
 *  skipped by React's reconciler. */
const AssistantMessageItem = memo(function AssistantMessageItem({
  msg,
}: {
  msg: ChatMessage;
}) {
  return (
    <div className="mb-4 group/msg relative flex justify-start">
      <div className="max-w-[min(720px,85%)] flex-1">
        <div className="markdown-body">
          <RichMarkdown isStreaming={msg.isStreaming}>{msg.content || ""}</RichMarkdown>
        </div>
      </div>
    </div>
  );
});

// ── UserInput helpers ─────────────────────────────────────────

function UserInputField({
  inputId,
  onSubmit,
}: {
  inputId: string;
  onSubmit: (id: string, answer: string) => void;
}) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const isComposingRef = useRef(false);
  const submit = (answer?: string) => {
    const text = answer || value.trim();
    if (!text) return;
    onSubmit(inputId, text);
    setValue("");
  };
  return (
    <div className="flex gap-2 mt-2">
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onCompositionStart={() => { isComposingRef.current = true; }}
        onCompositionEnd={() => { isComposingRef.current = false; }}
        onKeyDown={(e) => {
          if (e.key !== "Enter" || e.shiftKey) return;
          if (e.nativeEvent.isComposing || isComposingRef.current) return;
          e.preventDefault();
          submit();
        }}
        placeholder={t("chatPanel.typeAnswer")}
        autoFocus
        className="flex-1 h-8 px-3 text-xs rounded-md bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--brand)] focus:ring-2 focus:ring-[var(--brand)]/30"
      />
      <button
        onClick={() => submit()}
        disabled={!value.trim()}
        className="h-8 px-3 rounded-md text-xs font-medium bg-[var(--brand)] text-white disabled:opacity-40 hover:bg-[var(--brand-hover)] transition-colors"
      >
        Send
      </button>
    </div>
  );
}

function UserInputOptions({
  options,
  inputId,
  onSubmit,
}: {
  options: string[];
  inputId: string;
  onSubmit: (id: string, answer: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {options.map((opt, i) => (
        <button
          key={i}
          onClick={() => onSubmit(inputId, opt)}
          className="px-2.5 py-1 rounded-md text-xs font-medium bg-[var(--brand-bg)] text-[var(--brand)] border border-[var(--brand-border)] hover:bg-[var(--brand-bg-strong)] transition-colors"
        >
          {opt}
        </button>
      ))}
    </div>
  );
}

// ── Need useRef for UserInputField ────────────────────────────
// (already imported at top)

// ── Dispatcher ────────────────────────────────────────────────

export interface MessageItemProps extends MessageCallbacks {
  item: ChatMessage | [ChatMessage, ChatMessage] | ChatMessage[];
  sessionId?: string | null;
  replaying?: boolean;
  activeSubAgentId?: string | null;
  getSubAgentContent?: (subId: string) => string;
  onSubAgentClick?: (subAgentId: string | null) => void;
  onToggle?: () => void;
  showExecutionTree?: boolean;
  executionTreeToggle?: ReactNode;
}

/**
 * Single dispatcher component that renders one message or tool-call pair.
 * Memoized so that unchanged messages are skipped during streaming.
 *
 * React.memo does a shallow comparison of props. For `item`, we pass the
 * actual message object (or pair array), so React will skip re-render when
 * the reference is identical (which it is for all non-streaming messages,
 * since sseEventToMessages only creates new objects for changed messages).
 */
function MessageItemBase({
  item,
  sessionId,
  replaying,
  activeSubAgentId,
  getSubAgentContent,
  onSubAgentClick,
  onPreviewImage,
  onToolConfirm,
  onUserInput,
  onBranch,
  onToggle,
  executionTreeToggle,
}: MessageItemProps) {
  // ── Tool call + result pair ──
  if (Array.isArray(item)) {
    const [callMsg, resultMsg] = item;
    return (
      <ToolCallPairItem
        callMsg={callMsg}
        resultMsg={resultMsg}
        onPreviewImage={onPreviewImage}
        onToggle={onToggle}
      />
    );
  }

  const msg = item;

  switch (msg.role) {
    case "thinking":
      return <ThinkingItem msg={msg} onToggle={onToggle} />;

    case "tool_call":
      return <ToolCallItem msg={msg} onToggle={onToggle} />;

    case "tool_result":
    case "workspace":
      return null;

    case "stats":
      return (
        <div className="mb-4 ml-3">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-[11px] font-mono bg-[var(--bg-secondary)] border border-[var(--border)] text-[var(--text-secondary)]">
            <CheckCircle2 size={12} className="text-[var(--success)]" />
            {msg.stats && (() => {
              const s = msg.stats;
              const parts: string[] = [];
              if (s.model) parts.push(s.model);
              if (s.elapsed) parts.push(`${s.elapsed}s`);
              if (s.tokens) parts.push(`${s.tokens.toLocaleString()} tokens`);
              if (s.iterations) parts.push(`${s.iterations} iter`);
              return parts.map((p, idx) => (
                <span key={idx}>
                  {idx > 0 && <span className="text-[var(--border-strong)] mx-1">·</span>}
                  {p}
                </span>
              ));
            })()}
            {executionTreeToggle}
          </div>
        </div>
      );

    case "compress":
      return <CompressItem msg={msg} />;

    case "notice":
      return <NoticeItem msg={msg} />;

    case "tool_confirm":
      return <ToolConfirmItem msg={msg} onToolConfirm={onToolConfirm} />;

    case "user_input":
      return <UserInputItem msg={msg} onUserInput={onUserInput} />;

    case "sub_agent": {
      const completed = msg.sub_agent_elapsed !== undefined;
      const isActive = activeSubAgentId === msg.sub_agent_id;
      const liveContent = msg.sub_agent_id && getSubAgentContent
        ? getSubAgentContent(msg.sub_agent_id)
        : msg.content;
      return (
        <SubAgentCard
          agentName={msg.sub_agent_name}
          agentDisplay={msg.sub_agent_display || msg.sub_agent_name}
          task={msg.sub_agent_task}
          model={msg.sub_agent_model}
          status={completed ? "completed" : "running"}
          iterations={msg.sub_agent_iterations}
          elapsed={msg.sub_agent_elapsed}
          tokens={msg.sub_agent_tokens}
          content={liveContent || msg.content}
          isActive={isActive}
          expanded={isActive ? true : undefined}
          onClick={() => {
            if (isActive) onSubAgentClick?.(null);
            else onSubAgentClick?.(msg.sub_agent_id ?? msg.id);
          }}
        />
      );
    }

    case "error":
      return <ErrorItem msg={msg} />;

    case "retry":
      return <RetryItem msg={msg} />;

    case "screenshot":
      return <ScreenshotItem msg={msg} onPreviewImage={onPreviewImage} />;

    case "user":
      return (
        <UserMessageItem
          msg={msg}
          onPreviewImage={onPreviewImage}
          onBranch={onBranch}
          replaying={replaying}
        />
      );

    default:
      // assistant or unknown text role
      return <AssistantMessageItem msg={msg} />;
  }
}

export const MessageItem = memo(MessageItemBase);

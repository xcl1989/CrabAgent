import { forwardRef, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useTranslation } from "react-i18next";
import {
  Terminal,
  FileText,
  Pencil,
  Search,
  Sparkles,
  Plug,
  GitBranch,
  Check,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  MessageSquare,
  Bot,
  Loader2,
  Wrench,
  Zap,
  X,
  ArrowDown,
} from "lucide-react";
import { Modal } from "./ui";
import { RichMarkdown } from "./rich-content/RichMarkdown";
import ToolResultRender from "./ToolResultRender";
import { cn } from "../lib/cn";

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
  retry_info?: {
    phase: "retrying" | "countdown" | "exhausted";
    message: string;
    attempt: number;
    max_attempts: number;
    remaining_seconds?: number;
    delay_seconds?: number;
  };
}

interface Props {
  sessionId?: string | null;
  messages: ChatMessage[];
  connected: boolean;
  sending?: boolean;
  onToolConfirm?: (confirmId: string, approved: boolean) => void;
  onUserInput?: (inputId: string, answer: string) => void;
  onBranch?: (messageId: string) => void;
  replaying?: boolean;
  externalSubAgentId?: string | null;
  onSubAgentModalClose?: () => void;
  getSubAgentContent?: (subId: string) => string;
}

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
        onCompositionStart={() => {
          isComposingRef.current = true;
        }}
        onCompositionEnd={() => {
          isComposingRef.current = false;
        }}
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

const AGENT_ICONS: Record<string, ReactNode> = {
  researcher: <Search size={13} />,
  analyst: <Sparkles size={13} />,
  coder: <Terminal size={13} />,
  writer: <FileText size={13} />,
};

interface SubAgentSegment {
  type: "text" | "tool_call" | "tool_result";
  content: string;
  name?: string;
}

function parseSubAgentContent(raw: string): SubAgentSegment[] {
  const segments: SubAgentSegment[] = [];
  let remaining = raw;
  while (remaining.length > 0) {
    const callIdx = remaining.indexOf("\n→ ");
    const resultIdx = remaining.indexOf("\n← ");
    const nextSpecial = Math.min(
      callIdx >= 0 ? callIdx : Infinity,
      resultIdx >= 0 ? resultIdx : Infinity,
    );
    if (nextSpecial === Infinity) {
      if (remaining.trim()) {
        segments.push({ type: "text", content: remaining.trim() });
      }
      break;
    }
    if (nextSpecial > 0) {
      const textPart = remaining.slice(0, nextSpecial).trim();
      if (textPart) segments.push({ type: "text", content: textPart });
    }
    const isCall = callIdx >= 0 && (resultIdx < 0 || callIdx <= resultIdx);
    const marker = isCall ? "\n→ " : "\n← ";
    const start = remaining.indexOf(marker);
    const end = remaining.indexOf("\n→ ", start + 1);
    const end2 = remaining.indexOf("\n← ", start + 1);
    const blockEnd = Math.min(
      end >= 0 ? end : Infinity,
      end2 >= 0 ? end2 : Infinity,
    );
    const block =
      blockEnd === Infinity
        ? remaining.slice(start + marker.length)
        : remaining.slice(start + marker.length, blockEnd);
    if (isCall) {
      const colonIdx = block.indexOf("(");
      const name = colonIdx >= 0 ? block.slice(0, colonIdx) : block;
      const args = colonIdx >= 0 ? block.slice(colonIdx) : "()";
      segments.push({ type: "tool_call", content: args, name: name.trim() });
    } else {
      const colonIdx = block.indexOf(":");
      const name = colonIdx >= 0 ? block.slice(0, colonIdx) : "";
      const result = colonIdx >= 0 ? block.slice(colonIdx + 1) : block;
      segments.push({
        type: "tool_result",
        content: result.trim(),
        name: name.trim(),
      });
    }
    remaining = blockEnd === Infinity ? "" : remaining.slice(blockEnd);
  }
  return segments;
}

/* ---------- Main component ---------- */

const ChatPanel = forwardRef<HTMLDivElement, Props>(
  (
    {
      sessionId,
      messages,
      connected,
      sending,
      onToolConfirm,
      onUserInput,
      onBranch,
      replaying,
      externalSubAgentId,
      onSubAgentModalClose,
      getSubAgentContent,
    },
    _ref,
  ) => {
    const { t } = useTranslation();
    const [previewImage, setPreviewImage] = useState<string | null>(null);
    const [activeSubAgentId, setActiveSubAgentId] = useState<string | null>(
      null,
    );
    const [modalContent, setModalContent] = useState("");
    const modalContentRef = useRef("");

    // ── Smart auto-scroll (stable, jitter-free) ───────────────
    // Design principles:
    //  1. Streaming token updates use behavior:"auto" (instant), NOT "smooth"
    //     — smooth on every token creates overlapping animations → visual jumping
    //  2. "Pinned" threshold is small (24px) so users scrolling up a few px
    //     won't be snapped back to the bottom
    //  3. Programmatic scroll sets a guard flag so the onScroll handler
    //     doesn't re-evaluate pinning mid-animation
    //  4. useLayoutEffect (before paint) + rAF to avoid flash of wrong position
    //  5. ResizeObserver catches async height changes (images, markdown tables,
    //     code highlighting, <details> toggle)
    //  6. During active streaming (sending=true), onScroll does NOT unpin —
    //     only explicit wheel-up / touch-swipe-down can unpin. This prevents
    //     the race condition where content grows faster than scrollToBottom,
    //     momentarily pushing distanceFromBottom > threshold and causing
    //     a false "user left the bottom" detection.
    const scrollRef = useRef<HTMLDivElement>(null);
    const contentRef = useRef<HTMLDivElement>(null);
    const bottomRef = useRef<HTMLDivElement>(null);
    const isPinnedRef = useRef(true);
    const programmaticScrollRef = useRef(false);
    const rafRef = useRef<number | null>(null);
    const [showJumpBtn, setShowJumpBtn] = useState(false);
    const [newMsgHint, setNewMsgHint] = useState(0);

    // Synchronous mirror of `sending` for use in scroll event handlers
    const sendingRef = useRef(false);
    useEffect(() => { sendingRef.current = !!sending; }, [sending]);

    // Touch tracking for detecting swipe-up direction
    const touchStartYRef = useRef(0);

    const getDistanceFromBottom = useCallback(() => {
      const el = scrollRef.current;
      if (!el) return 0;
      return el.scrollHeight - el.scrollTop - el.clientHeight;
    }, []);

    /** Scroll to bottom instantly (for streaming) or smoothly (for user click). */
    const scrollToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
      const el = scrollRef.current;
      if (!el) return;
      programmaticScrollRef.current = true;
      el.scrollTo({ top: el.scrollHeight, behavior });
      // For smooth scrolls, keep the guard active until the animation settles
      const ms = behavior === "smooth" ? 300 : 32;
      window.setTimeout(() => { programmaticScrollRef.current = false; }, ms);
    }, []);

    /** onScroll: update pinning state. Ignores programmatic scrolls.
     *  During streaming, does NOT unpin — only explicit user gestures can. */
    const handleScroll = useCallback(() => {
      if (programmaticScrollRef.current) return;
      // During active streaming, content growth between frames can momentarily
      // push distanceFromBottom above threshold even though the user hasn't
      // scrolled up. Defer all unpinning to the wheel/touch handlers.
      if (sendingRef.current) return;
      const dist = getDistanceFromBottom();
      const pinned = dist <= 24;
      isPinnedRef.current = pinned;
      setShowJumpBtn(!pinned);
      if (pinned) setNewMsgHint(0);
    }, [getDistanceFromBottom]);

    /** Wheel handler: detect scroll DIRECTION (not distance).
     *  deltaY < 0 → user scrolling up → unpin immediately.
     *  deltaY > 0 → user scrolling down → re-pin if near bottom. */
    const onWheelIntent = useCallback((e: React.WheelEvent) => {
      if (programmaticScrollRef.current) return;
      if (e.deltaY < 0) {
        // User is actively scrolling away from the bottom
        isPinnedRef.current = false;
        setShowJumpBtn(true);
      } else if (e.deltaY > 0) {
        // User scrolling toward bottom — re-pin if close enough
        if (getDistanceFromBottom() <= 24) {
          isPinnedRef.current = true;
          setShowJumpBtn(false);
          setNewMsgHint(0);
        }
      }
    }, [getDistanceFromBottom]);

    /** Touch handlers: detect swipe direction by tracking Y delta. */
    const onTouchStartRecord = useCallback((e: React.TouchEvent) => {
      touchStartYRef.current = e.touches[0]?.clientY ?? 0;
    }, []);

    const onTouchMoveIntent = useCallback((e: React.TouchEvent) => {
      if (programmaticScrollRef.current) return;
      const currentY = e.touches[0]?.clientY ?? 0;
      const delta = currentY - touchStartYRef.current;
      // Finger moving down (positive delta) = content scrolling up = user reading history
      if (delta > 5) {
        isPinnedRef.current = false;
        setShowJumpBtn(true);
      }
      // Finger moving up (negative delta) = content scrolling down = toward bottom
      if (delta < -5 && getDistanceFromBottom() <= 24) {
        isPinnedRef.current = true;
        setShowJumpBtn(false);
        setNewMsgHint(0);
      }
    }, [getDistanceFromBottom]);

    // Auto-scroll on messages / sending changes — runs before browser paint
    // Uses throttle (skip if already scheduled) instead of cancel-and-reschedule.
    // The old approach cancelled the pending rAF on every message update, which
    // meant during rapid streaming the rAF never fired — especially problematic
    // when content first exceeds the viewport (first conversation).
    useLayoutEffect(() => {
      if (rafRef.current) return; // Already scheduled — will fire next frame
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = null;
        if (isPinnedRef.current) {
          scrollToBottom("auto");
        } else {
          setNewMsgHint((n) => n + 1);
        }
      });
    }, [messages, sending, scrollToBottom]);

    // ResizeObserver: catch async DOM height changes (image load, code
    // highlighting, markdown table reflow, <details> expand)
    useEffect(() => {
      const el = contentRef.current;
      if (!el) return;
      const observer = new ResizeObserver(() => {
        if (!isPinnedRef.current) return;
        requestAnimationFrame(() => scrollToBottom("auto"));
      });
      observer.observe(el);
      return () => observer.disconnect();
    }, [scrollToBottom]);

    // Reset scroll state on session change
    useLayoutEffect(() => {
      isPinnedRef.current = true;
      setShowJumpBtn(false);
      setNewMsgHint(0);
      scrollToBottom("auto");
    }, [sessionId, scrollToBottom]);

    const jumpToBottom = useCallback(() => {
      isPinnedRef.current = true;
      setShowJumpBtn(false);
      setNewMsgHint(0);
      scrollToBottom("smooth");
    }, [scrollToBottom]);

    // Helper: scroll to bottom if user is currently at bottom (for details toggle)
    const maybeScrollOnToggle = useCallback(() => {
      if (isPinnedRef.current) {
        requestAnimationFrame(() => scrollToBottom("auto"));
      }
    }, [scrollToBottom]);
    const modalTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const resolvedSubAgentId = externalSubAgentId ?? activeSubAgentId;
    const closeSubAgent = () => {
      setActiveSubAgentId(null);
      setModalContent("");
      modalContentRef.current = "";
      onSubAgentModalClose?.();
    };

    useEffect(() => {
      if (!resolvedSubAgentId || !getSubAgentContent) return;
      const newContent = getSubAgentContent(resolvedSubAgentId);
      if (!newContent || newContent === modalContentRef.current) return;
      modalContentRef.current = newContent;
      if (!modalTimerRef.current) {
        setModalContent(newContent);
        modalTimerRef.current = setTimeout(() => {
          modalTimerRef.current = null;
          if (!resolvedSubAgentId || !getSubAgentContent) return;
          const c = getSubAgentContent(resolvedSubAgentId);
          if (c && c !== modalContentRef.current) {
            modalContentRef.current = c;
            setModalContent(c);
          }
        }, 500);
      }
    }, [resolvedSubAgentId, getSubAgentContent]);

    useEffect(() => {
      return () => {
        if (modalTimerRef.current) clearTimeout(modalTimerRef.current);
      };
    }, []);

    const grouped = useMemo(() => {
      const result: (ChatMessage | ChatMessage[])[] = [];
      const consumedToolResults = new Set<string>();
      for (let i = 0; i < messages.length; i += 1) {
        const msg = messages[i];
        if (msg.role === "tool_call") {
          const matchIdx = messages.findIndex(
            (candidate, idx) =>
              idx > i &&
              candidate.role === "tool_result" &&
              !consumedToolResults.has(candidate.id) &&
              !!candidate.tool_call_id &&
              candidate.tool_call_id === msg.tool_call_id,
          );
          if (matchIdx >= 0) {
            const resultMsg = messages[matchIdx];
            consumedToolResults.add(resultMsg.id);
            result.push([msg, resultMsg]);
            continue;
          }
        }
        if (msg.role === "tool_result" && consumedToolResults.has(msg.id)) {
          continue;
        }
        result.push(msg);
      }
      return result;
    }, [messages]);

    return (
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        onWheel={onWheelIntent}
        onTouchStart={onTouchStartRecord}
        onTouchMove={onTouchMoveIntent}
        className="chat-scroll flex-1 min-h-0 overflow-y-auto overscroll-contain px-3 sm:px-6 py-3 sm:py-4 relative"
      >
        <div ref={contentRef}>
        {!connected && messages.length > 0 && (
          <div className="flex items-center justify-center gap-2 mb-3 text-xs text-[var(--warning)] bg-[var(--warning-bg)] border border-[var(--warning-border)] rounded-lg px-3 py-1.5">
            <Loader2 size={12} className="animate-spin" />
            <span>{t("chatPanel.reconnecting")}</span>
          </div>
        )}

        {grouped.map((item) => {
          if (Array.isArray(item)) {
            const [callMsg, resultMsg] = item;
            const { name, summary } = getToolSummary(callMsg.content);
            const isMcp = callMsg.source === "mcp";
            const displayName = isMcp
              ? name.replace(/^mcp__/, "").replace(/__/g, ": ")
              : name;
            const accentVar = isMcp ? "var(--accent-2)" : "var(--accent)";

            return (
              <details
                key={callMsg.id}
                className="mb-3 group ml-3 rounded-lg overflow-hidden"
                onToggle={(e) => { if (e.currentTarget.open) maybeScrollOnToggle(); }}
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
                  <span
                    className="font-medium truncate"
                    style={{ color: accentVar }}
                  >
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
                  onPreviewImage={(url) => setPreviewImage(url)}
                  accentVar={accentVar}
                />
              </details>
            );
          }

          const msg = item;

          if (msg.role === "thinking") {
            return (
              <details
                key={msg.id}
                className="mb-3 ml-3 rounded-lg overflow-hidden"
                onToggle={(e) => { if (e.currentTarget.open) maybeScrollOnToggle(); }}
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
          }

          if (msg.role === "tool_call") {
            const { name, summary } = getToolSummary(msg.content);
            const isMcp = msg.source === "mcp";
            const displayName = isMcp
              ? name.replace(/^mcp__/, "").replace(/__/g, ": ")
              : name;
            const accentVar = isMcp ? "var(--accent-2)" : "var(--accent)";
            const bashStream = (msg as any).bashStream as string | undefined;
            const isBashStreaming = name === "bash" && bashStream;
            return (
              <details
                key={msg.id}
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
          }

          if (msg.role === "tool_result") return null;
          if (msg.role === "workspace") return null;

          if (msg.role === "stats" && msg.stats) {
            const s = msg.stats;
            const parts: string[] = [];
            if (s.model) parts.push(s.model);
            if (s.elapsed) parts.push(`${s.elapsed}s`);
            if (s.tokens) parts.push(`${s.tokens.toLocaleString()} tokens`);
            if (s.iterations) parts.push(`${s.iterations} iter`);
            return (
              <div key={msg.id} className="mb-4 ml-3">
                <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-[11px] font-mono bg-[var(--bg-secondary)] border border-[var(--border)] text-[var(--text-secondary)]">
                  <CheckCircle2 size={12} className="text-[var(--success)]" />
                  {parts.map((p, idx) => (
                    <span key={idx}>
                      {idx > 0 && (
                        <span className="text-[var(--border-strong)] mx-1">·</span>
                      )}
                      {p}
                    </span>
                  ))}
                </div>
              </div>
            );
          }

          if (msg.role === "compress") {
            return (
              <div key={msg.id} className="mb-3 flex justify-center">
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
          }

          if (msg.role === "notice") {
            return (
              <div key={msg.id} className="mb-3 ml-3">
                <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs bg-[var(--warning-bg)] border border-[var(--warning-border)] text-[var(--warning)]">
                  <AlertTriangle size={12} />
                  {msg.content}
                </div>
              </div>
            );
          }

          if (msg.role === "tool_confirm" && msg.confirm_id) {
            const resolved = msg.confirmed !== undefined;
            return (
              <div key={msg.id} className="mb-3 ml-3">
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
                          <>
                            <Check size={12} /> Allowed
                          </>
                        ) : (
                          <>
                            <X size={12} /> Denied
                          </>
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
          }

          if (msg.role === "user_input" && msg.confirm_id) {
            const resolved = msg.confirmed !== undefined;
            const options = msg.options;
            return (
              <div key={msg.id} className="mb-3 ml-3">
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
                    <UserInputOptions
                      options={options}
                      inputId={msg.confirm_id}
                      onSubmit={onUserInput}
                    />
                  )}
                  {!resolved &&
                    onUserInput &&
                    (!options || options.length === 0) && (
                      <UserInputField
                        inputId={msg.confirm_id}
                        onSubmit={onUserInput}
                      />
                    )}
                  {resolved && (
                    <div className="text-xs mt-1 text-[var(--text-secondary)]">
                      → {msg.content}
                    </div>
                  )}
                </div>
              </div>
            );
          }

          if (msg.role === "sub_agent") {
            const completed = msg.sub_agent_elapsed !== undefined;
            const isActive = resolvedSubAgentId === msg.sub_agent_id;
            const agentIcon =
              AGENT_ICONS[msg.sub_agent_name || ""] || <Bot size={13} />;
            return (
              <button
                key={msg.id}
                onClick={() => {
                  if (isActive) closeSubAgent();
                  else setActiveSubAgentId(msg.sub_agent_id ?? msg.id);
                }}
                className={cn(
                  "mb-3 ml-3 flex items-center gap-2 cursor-pointer py-1.5 px-3 rounded-lg text-xs select-none transition-all",
                  isActive
                    ? "bg-[var(--accent-2-bg)] border-[var(--accent-2)] text-[var(--accent-2)]"
                    : "bg-[var(--bg-secondary)] border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--border-strong)]",
                  "border",
                )}
              >
                <span className="shrink-0">{agentIcon}</span>
                <span className="font-medium text-[var(--text-primary)] truncate">
                  {msg.sub_agent_display || msg.sub_agent_name}
                </span>
                {completed ? (
                  <CheckCircle2
                    size={12}
                    className="text-[var(--success)] shrink-0"
                  />
                ) : (
                  <Loader2
                    size={11}
                    className="animate-spin text-[var(--accent-2)] shrink-0"
                  />
                )}
                {completed && (
                  <span className="text-[10px] text-[var(--text-tertiary)] font-mono">
                    {msg.sub_agent_iterations} steps · {msg.sub_agent_elapsed}s ·{" "}
                    {msg.sub_agent_tokens} tok
                  </span>
                )}
                {!completed && (
                  <span className="text-[10px] text-[var(--accent-2)] animate-pulse">
                    running…
                  </span>
                )}
              </button>
            );
          }

          if (msg.role === "error") {
            return (
              <div key={msg.id} className="mb-3">
                <div className="flex items-start gap-2 px-4 py-3 rounded-xl text-sm bg-[var(--danger-bg)] border border-[var(--danger-border)] text-[var(--danger)]">
                  <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                  <div className="whitespace-pre-wrap break-words">{msg.content}</div>
                </div>
              </div>
            );
          }

          if (msg.role === "retry" && msg.retry_info) {
            const ri = msg.retry_info;
            const isCountdown = ri.phase === "countdown";
            const remaining = ri.remaining_seconds ?? 0;
            const totalDelay = ri.delay_seconds ?? 0;
            const progress = totalDelay > 0 ? ((totalDelay - remaining) / totalDelay) * 100 : 0;

            return (
              <div key={msg.id} className="mb-3">
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
          }

          if (msg.role === "screenshot") {
            return (
              <div key={msg.id} className="mb-3 ml-3 flex flex-wrap gap-2">
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
                    onClick={() => setPreviewImage(img)}
                    onError={(e) => {
                      const target = e.currentTarget;
                      target.style.display = "none";
                    }}
                  />
                ))}
              </div>
            );
          }

          const isUser = msg.role === "user";

          return (
            <div
              key={msg.id}
              className={cn(
                "mb-4 group/msg relative flex",
                isUser ? "justify-end" : "justify-start",
              )}
            >
              {isUser ? (
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
                          onClick={() => setPreviewImage(img)}
                          alt=""
                        />
                      ))}
                    </div>
                  )}
                  <p className="whitespace-pre-wrap leading-relaxed text-[14px]">
                    {msg.content}
                  </p>
                  {onBranch &&
                    !replaying &&
                    !msg.isStreaming &&
                    msg.id.startsWith("db-") && (
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
              ) : (
                <div className="max-w-[min(720px,85%)] flex-1">
                  <div className="markdown-body">
                    <RichMarkdown>{msg.content || ""}</RichMarkdown>
                  </div>
                </div>
              )}
            </div>
          );
        })}

        {sending && !replaying && (
          <div className="flex items-center px-1 py-1">
            <span className="text-[var(--brand)] animate-pulse select-none">🦀</span>
          </div>
        )}

        {/* Scroll sentinel — also serves as CSS scroll-anchor target */}
        <div ref={bottomRef} className="chat-scroll-sentinel" />
        </div>{/* end contentRef wrapper */}

        {/* Jump-to-bottom floating button */}
        {showJumpBtn && (
          <div className="sticky bottom-4 flex justify-center z-30 pointer-events-none">
            <button
              onClick={jumpToBottom}
              className="pointer-events-auto flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-[var(--brand)] text-white shadow-lg hover:bg-[var(--brand-hover)] transition-all"
            >
              <ArrowDown size={13} />
              {newMsgHint > 0 && (
                <span className="px-1.5 py-0.5 rounded-full bg-white/20 text-[10px]">
                  {newMsgHint > 9 ? "9+" : newMsgHint}
                </span>
              )}
            </button>
          </div>
        )}

        {/* Image lightbox */}
        <Modal
          open={!!previewImage}
          onOpenChange={(o) => !o && setPreviewImage(null)}
          size="full"
          hideClose
          title={null}
        >
          <div
            className="flex items-center justify-center -mx-5 -my-4 cursor-zoom-out"
            onClick={() => setPreviewImage(null)}
            style={{ minHeight: "70vh" }}
          >
            {previewImage && (
              <img
                src={previewImage}
                alt="Preview"
                className="max-w-full max-h-[80vh] object-contain rounded-lg"
              />
            )}
          </div>
        </Modal>

        {/* Sub-agent live stream modal */}
        {resolvedSubAgentId &&
          (() => {
            const agent = messages.find(
              (m) =>
                m.sub_agent_id === resolvedSubAgentId ||
                m.id === resolvedSubAgentId,
            );
            if (!agent) return null;
            const completed = agent.sub_agent_elapsed !== undefined;
            const agentIcon =
              AGENT_ICONS[agent.sub_agent_name || ""] || <Bot size={16} />;
            return (
              <Modal
                open={true}
                onOpenChange={(o) => !o && closeSubAgent()}
                size="lg"
                title={
                  <div className="flex items-center gap-2">
                    <span className="text-[var(--accent-2)]">{agentIcon}</span>
                    <span>{agent.sub_agent_display || agent.sub_agent_name}</span>
                    {!completed && (
                      <span className="flex items-center gap-1 ml-1 text-xs text-[var(--accent-2)]">
                        <Loader2 size={12} className="animate-spin" />
                        running…
                      </span>
                    )}
                  </div>
                }
                description={
                  completed
                    ? `${agent.sub_agent_iterations} steps · ${agent.sub_agent_elapsed}s · ${agent.sub_agent_tokens} tokens`
                    : undefined
                }
              >
                <SubAgentBody content={modalContent} />
              </Modal>
            );
          })()}
      </div>
    );
  },
);

function SubAgentBody({ content }: { content: string }) {
  const segments = parseSubAgentContent(content);
  if (segments.length === 0) {
    return (
      <div className="flex items-center justify-center gap-2 py-8 text-sm text-[var(--text-tertiary)]">
        <Loader2 size={14} className="animate-spin" />
        <span>working…</span>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {segments.map((seg, i) => {
        if (seg.type === "text") {
          return (
            <div
              key={i}
              className="text-sm whitespace-pre-wrap leading-relaxed text-[var(--text-primary)]"
            >
              {seg.content}
            </div>
          );
        }
        if (seg.type === "tool_call") {
          return (
            <div
              key={i}
              className="flex items-center gap-2 py-1.5 px-3 rounded-md text-xs bg-[var(--bg-tertiary)] border border-[var(--border)]"
            >
              <Zap size={12} className="text-[var(--accent-2)] shrink-0" />
              <span className="font-medium text-[var(--accent-2)] shrink-0">
                {seg.name}
              </span>
              <span className="text-[var(--text-tertiary)] font-mono truncate">
                {seg.content}
              </span>
            </div>
          );
        }
        if (seg.type === "tool_result") {
          return (
            <div
              key={i}
              className="rounded-md overflow-hidden bg-[var(--bg-tertiary)] border-l-[3px] border-l-[var(--success)]"
            >
              <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--success)] flex items-center gap-1.5">
                <CheckCircle2 size={11} /> {seg.name}
              </div>
              <pre className="px-3 py-2 text-[12px] whitespace-pre-wrap break-all leading-relaxed font-mono text-[var(--text-secondary)] m-0 max-h-48 overflow-auto bg-transparent! border-0!">
                {seg.content}
              </pre>
            </div>
          );
        }
        return null;
      })}
    </div>
  );
}

ChatPanel.displayName = "ChatPanel";
export default ChatPanel;

import { forwardRef, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { useTranslation } from "react-i18next";
import {
  Loader2,
  ArrowDown,
  Activity,
  X,
} from "lucide-react";
import { Modal } from "./ui";
import ExecutionTreePanel from "./ExecutionTreePanel";
import { MessageItem } from "./MessageItem";

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
    // Tick state to force re-render of the active sub-agent card while the
    // live content stream (stored in a ref outside React) keeps growing.
    const [liveTick, setLiveTick] = useState(0);

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

    // Synchronous mirror of `sending` for use in scroll event handlers.
    // Updated during render (not in useEffect) so the ref is always current
    // when scroll/wheel events fire between commit and effect cleanup.
    const sendingRef = useRef(false);
    sendingRef.current = !!sending;

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
     *  deltaY > 0 → user scrolling down → re-pin if near bottom.
     *  NOTE: Do NOT check programmaticScrollRef here — wheel is a user
     *  intent gesture and must always take precedence over programmatic
     *  scroll-to-bottom. Checking the guard caused the ref to stay true
     *  100% of the time during streaming (32ms timeout < 16ms frame interval),
     *  making scrolling completely unresponsive. */
    const onWheelIntent = useCallback((e: React.WheelEvent) => {
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

    /** Touch handlers: detect swipe direction by tracking Y delta.
     *  NOTE: Do not check programmaticScrollRef — touch is a user intent gesture. */
    const onTouchStartRecord = useCallback((e: React.TouchEvent) => {
      touchStartYRef.current = e.touches[0]?.clientY ?? 0;
    }, []);

    const onTouchMoveIntent = useCallback((e: React.TouchEvent) => {
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
      onSubAgentModalClose?.();
    };

    // Poll the live content ref for the active sub-agent to force a re-render
    // (the content map is a ref, so updates don't trigger React re-render).
    useEffect(() => {
      if (!resolvedSubAgentId || !getSubAgentContent) return;
      modalTimerRef.current = setInterval(() => {
        setLiveTick((t) => t + 1);
      }, 300);
      return () => {
        if (modalTimerRef.current) {
          clearInterval(modalTimerRef.current);
          modalTimerRef.current = null;
        }
      };
    }, [resolvedSubAgentId, getSubAgentContent]);

    // Reference liveTick so the linter doesn't complain; the interval
    // bumps this counter to trigger re-renders during streaming.
    void liveTick;

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
          const key = Array.isArray(item) ? item[0].id : item.id;
          return (
            <MessageItem
              key={key}
              item={item}
              sessionId={sessionId}
              replaying={replaying}
              activeSubAgentId={resolvedSubAgentId}
              getSubAgentContent={getSubAgentContent}
              onSubAgentClick={(sid) => sid ? setActiveSubAgentId(sid) : closeSubAgent()}
              onPreviewImage={(url) => setPreviewImage(url)}
              onToolConfirm={onToolConfirm}
              onUserInput={onUserInput}
              onBranch={onBranch}
              onToggle={maybeScrollOnToggle}
              executionTreeToggle={
                sessionId && !Array.isArray(item) && item.role === "stats"
                  ? <ExecutionTreeToggle sessionId={sessionId} />
                  : undefined
              }
            />
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

      </div>
    );
  },
);

ChatPanel.displayName = "ChatPanel";

// ── Execution tree toggle ──
function ExecutionTreeToggle({ sessionId }: { sessionId: string }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <span className="text-[var(--border-strong)] mx-1">·</span>
      <button
        className="inline-flex items-center gap-0.5 text-[var(--brand)] hover:underline"
        onClick={(e) => {
          e.stopPropagation();
          setOpen(!open);
        }}
      >
        <Activity size={11} />
        {open ? "Hide trace" : "Trace"}
      </button>
      {open && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={() => setOpen(false)}>
          <div
            className="w-full max-w-md h-full bg-[var(--bg-primary)] border-l border-[var(--border)] overflow-y-auto shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="sticky top-0 flex items-center justify-between px-4 py-3 border-b border-[var(--border)] bg-[var(--bg-primary)] z-10">
              <span className="text-sm font-semibold flex items-center gap-1.5">
                <Activity size={15} className="text-[var(--brand)]" />
                Execution Trace
              </span>
              <button
                className="p-1 rounded hover:bg-[var(--bg-tertiary)]"
                onClick={() => setOpen(false)}
              >
                <X size={15} className="text-[var(--text-tertiary)]" />
              </button>
            </div>
            <div className="p-3">
              <ExecutionTreePanel sessionId={sessionId} />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
export default ChatPanel;

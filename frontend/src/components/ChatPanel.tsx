import { forwardRef, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

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
  images?: string[];
  sub_agent_id?: string;
  sub_agent_name?: string;
  sub_agent_display?: string;
  sub_agent_elapsed?: number;
  sub_agent_tokens?: number;
  sub_agent_iterations?: number;
}

interface Props {
  messages: ChatMessage[];
  connected: boolean;
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
    const summary = firstKey ? String(args[firstKey]).slice(0, 80) : "";
    return { name, summary };
  } catch {
    return { name: "unknown", summary: content.slice(0, 80) };
  }
}

const TOOL_ICONS: Record<string, string> = {
  bash: "$_",
  read: "📖",
  write: "✏️",
  edit: "🔧",
  glob: "🔍",
  grep: "🔎",
  skill: "📋",
};

function ToolCallSummary({ name, summary, source, server_name }: { name: string; summary: string; source?: string; server_name?: string }) {
  const isMcp = source === "mcp";
  const icon = isMcp ? "🔌" : (TOOL_ICONS[name] || "⚡");
  const displayName = isMcp ? name.replace(/^mcp__/, "").replace(/__/g, ": ") : name;
  const accentColor = isMcp ? "var(--accent-2)" : "var(--accent)";
  const borderColor = isMcp ? "var(--accent-2)" : "var(--accent)";

  return { icon, displayName, accentColor, borderColor, isMcp, serverLabel: isMcp && server_name ? `[MCP: ${server_name}]` : "" };
}

function UserInputField({ inputId, onSubmit }: { inputId: string; onSubmit: (id: string, answer: string) => void }) {
  const [value, setValue] = useState("");
  const handleSubmit = (answer?: string) => {
    const text = answer || value.trim();
    if (!text) return;
    onSubmit(inputId, text);
    setValue("");
  };
  return (
    <div className="mt-2">
      <div className="flex gap-2">
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSubmit();
            }
          }}
          placeholder="Type your answer..."
          className="flex-1 px-3 py-1.5 rounded text-xs outline-none"
          style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
          autoFocus
        />
        <button
          onClick={() => handleSubmit()}
          disabled={!value.trim()}
          className="px-3 py-1.5 rounded text-xs font-medium text-white disabled:opacity-50"
          style={{ background: "var(--accent)" }}
        >
          Send
        </button>
      </div>
    </div>
  );
}

function UserInputOptions({ options, inputId, onSubmit }: { options: string[]; inputId: string; onSubmit: (id: string, answer: string) => void }) {
  return (
    <div className="flex flex-wrap gap-2 mt-2">
      {options.map((opt, i) => (
        <button
          key={i}
          onClick={() => onSubmit(inputId, opt)}
          className="px-3 py-1.5 rounded text-xs font-medium"
          style={{ background: "var(--accent)", color: "var(--text-on-accent)" }}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}

const AGENT_ICONS: Record<string, string> = {
  researcher: "🔍",
  analyst: "📊",
  coder: "💻",
  writer: "📝",
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
      resultIdx >= 0 ? resultIdx : Infinity
    );

    if (nextSpecial === Infinity) {
      if (remaining.trim()) {
        segments.push({ type: "text", content: remaining.trim() });
      }
      break;
    }

    if (nextSpecial > 0) {
      const textPart = remaining.slice(0, nextSpecial).trim();
      if (textPart) {
        segments.push({ type: "text", content: textPart });
      }
    }

    const isCall = callIdx >= 0 && (resultIdx < 0 || callIdx <= resultIdx);
    const marker = isCall ? "\n→ " : "\n← ";
    const start = remaining.indexOf(marker);
    const end = remaining.indexOf("\n→ ", start + 1);
    const end2 = remaining.indexOf("\n← ", start + 1);
    const blockEnd = Math.min(end >= 0 ? end : Infinity, end2 >= 0 ? end2 : Infinity);
    const block = blockEnd === Infinity ? remaining.slice(start + marker.length) : remaining.slice(start + marker.length, blockEnd);

    if (isCall) {
      const colonIdx = block.indexOf("(");
      const name = colonIdx >= 0 ? block.slice(0, colonIdx) : block;
      const args = colonIdx >= 0 ? block.slice(colonIdx) : "()";
      segments.push({ type: "tool_call", content: args, name: name.trim() });
    } else {
      const colonIdx = block.indexOf(":");
      const name = colonIdx >= 0 ? block.slice(0, colonIdx) : "";
      const result = colonIdx >= 0 ? block.slice(colonIdx + 1) : block;
      segments.push({ type: "tool_result", content: result.trim(), name: name.trim() });
    }

    remaining = blockEnd === Infinity ? "" : remaining.slice(blockEnd);
  }

  return segments;
}

const ChatPanel = forwardRef<HTMLDivElement, Props>(({ messages, connected, onToolConfirm, onUserInput, onBranch, replaying, externalSubAgentId, onSubAgentModalClose, getSubAgentContent }, bottomRef) => {
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  const [activeSubAgentId, setActiveSubAgentId] = useState<string | null>(null);
  const [modalContent, setModalContent] = useState("");
  const modalContentRef = useRef("");
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
  const grouped: (ChatMessage | ChatMessage[])[] = [];
  let i = 0;
  while (i < messages.length) {
    const msg = messages[i];
    if (msg.role === "tool_call" && i + 1 < messages.length && messages[i + 1].role === "tool_result") {
      grouped.push([msg, messages[i + 1]]);
      i += 2;
    } else {
      grouped.push(msg);
      i += 1;
    }
  }

  return (
    <div className="flex-1 overflow-y-auto px-6 py-4">
      {!connected && messages.length > 0 && (
        <div className="text-xs text-center mb-2" style={{ color: "var(--text-secondary)" }}>
          Reconnecting...
        </div>
      )}

      {grouped.map((item, idx) => {
        if (Array.isArray(item)) {
          const [callMsg, resultMsg] = item;
          const { name, summary } = getToolSummary(callMsg.content);
          const meta = ToolCallSummary({ name, summary, source: callMsg.source, server_name: callMsg.server_name });

          return (
            <details
              key={callMsg.id}
              className="mb-3 group"
              style={{ marginLeft: "12px" }}
            >
              <summary
                className="flex items-center gap-2 cursor-pointer py-1.5 px-3 rounded-md text-xs select-none"
                style={{
                  background: "var(--bg-secondary)",
                  border: "1px solid var(--border)",
                  color: "var(--text-secondary)",
                }}
              >
                <span style={{ color: meta.accentColor, fontFamily: "monospace", fontSize: "11px" }}>{meta.icon}</span>
                <span className="font-medium" style={{ color: meta.isMcp ? "#c4b5fd" : "var(--accent)" }}>{meta.displayName}</span>
                {meta.serverLabel && (
                  <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: "var(--accent-2-bg)", color: "var(--accent-2)", fontSize: "10px" }}>
                    {meta.serverLabel}
                  </span>
                )}
                {summary && (
                  <span style={{ color: "var(--text-secondary)", fontFamily: "monospace" }}>
                    {summary}
                  </span>
                )}
              </summary>

              <div
                className="mt-1.5 rounded-md overflow-hidden"
                style={{
                  borderLeft: `3px solid ${meta.borderColor}`,
                  background: "var(--bg-secondary)",
                }}
              >
                <div className="px-3 py-2">
                  <div className="text-xs font-medium mb-1" style={{ color: "var(--text-secondary)" }}>
                    Arguments
                  </div>
                  <pre
                    className="text-xs whitespace-pre-wrap break-all leading-relaxed"
                    style={{ color: "var(--text-primary)", fontFamily: "'SF Mono', 'Fira Code', monospace", fontSize: "12px" }}
                  >
                    {(() => {
                      try {
                        return JSON.stringify(JSON.parse(callMsg.content).arguments, null, 2);
                      } catch {
                        return callMsg.content;
                      }
                    })()}
                  </pre>
                </div>

                <div
                  className="px-3 py-2"
                  style={{ borderTop: "1px solid var(--border)" }}
                >
                  <div className="text-xs font-medium mb-1" style={{ color: "var(--text-secondary)" }}>
                    Result
                  </div>
                  <pre
                    className="text-xs whitespace-pre-wrap break-all leading-relaxed"
                    style={{
                      color: "var(--text-secondary)",
                      fontFamily: "'SF Mono', 'Fira Code', monospace",
                      fontSize: "12px",
                      maxHeight: "200px",
                      overflow: "auto",
                    }}
                  >
                    {resultMsg.content.slice(0, 2000)}
                  </pre>
                </div>
              </div>
            </details>
          );
        }

        const msg = item;

        if (msg.role === "thinking") {
          return (
            <details key={msg.id} className="mb-3" style={{ marginLeft: "12px" }}>
              <summary
                className="cursor-pointer py-1 px-3 text-xs rounded-md select-none"
                style={{ color: "var(--text-secondary)", background: "var(--bg-secondary)", border: "1px solid var(--border)" }}
              >
                💭 Thinking...
              </summary>
              <div
                className="mt-1.5 p-3 rounded-md text-xs leading-relaxed"
                style={{
                  background: "var(--bg-secondary)",
                  borderLeft: "3px solid var(--accent-2)",
                  color: "var(--text-secondary)",
                }}
              >
                <pre className="whitespace-pre-wrap" style={{ fontFamily: "'SF Mono', monospace", fontSize: "12px" }}>
                  {msg.content}
                </pre>
              </div>
            </details>
          );
        }

        if (msg.role === "tool_call") {
          const { name, summary } = getToolSummary(msg.content);
          const meta = ToolCallSummary({ name, summary, source: msg.source, server_name: msg.server_name });
          return (
            <details key={msg.id} className="mb-3" style={{ marginLeft: "12px" }}>
              <summary
                className="flex items-center gap-2 cursor-pointer py-1.5 px-3 rounded-md text-xs select-none"
                style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", color: "var(--text-secondary)" }}
              >
                <span style={{ color: meta.accentColor, fontFamily: "monospace", fontSize: "11px" }}>{meta.icon}</span>
                <span className="font-medium" style={{ color: meta.isMcp ? "#c4b5fd" : "var(--accent)" }}>{meta.displayName}</span>
                {meta.serverLabel && (
                  <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: "var(--accent-2-bg)", color: "var(--accent-2)", fontSize: "10px" }}>
                    {meta.serverLabel}
                  </span>
                )}
                {summary && <span style={{ color: "var(--text-secondary)", fontFamily: "monospace" }}>{summary}</span>}
              </summary>
            </details>
          );
        }

        if (msg.role === "tool_result") {
          return null;
        }

        if (msg.role === "stats" && msg.stats) {
          const s = msg.stats;
          const parts: string[] = [];
          if (s.model) parts.push(s.model);
          if (s.elapsed) parts.push(`${s.elapsed}s`);
          if (s.tokens) parts.push(`${s.tokens.toLocaleString()} tokens`);
          if (s.iterations) parts.push(`${s.iterations} iter`);
          return (
            <div key={msg.id} className="mb-4" style={{ marginLeft: "12px" }}>
              <div
                className="inline-flex items-center gap-3 px-3 py-1.5 rounded-full text-xs select-none"
                style={{
                  background: "var(--bg-secondary)",
                  border: "1px solid var(--border)",
                  color: "var(--text-secondary)",
                  fontFamily: "'SF Mono', 'Fira Code', monospace",
                }}
              >
                <span style={{ color: "var(--success)" }}>✓</span>
                {parts.map((p, i) => (
                  <span key={i}>
                    {i > 0 && <span style={{ color: "var(--border)", margin: "0 2px" }}>·</span>}
                    {p}
                  </span>
                ))}
              </div>
            </div>
          );
        }

        if (msg.role === "notice") {
          return (
            <div key={msg.id} className="mb-3" style={{ marginLeft: "12px" }}>
              <div
                className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs select-none"
                style={{
                  background: "var(--bg-secondary)",
                  border: "1px solid var(--border)",
                  color: "var(--warning)",
                  fontFamily: "'SF Mono', 'Fira Code', monospace",
                }}
              >
                <span>◐</span>
                {msg.content}
              </div>
            </div>
          );
        }

        if (msg.role === "tool_confirm" && msg.confirm_id) {
          const resolved = msg.confirmed !== undefined;
          return (
            <div key={msg.id} className="mb-3" style={{ marginLeft: "12px" }}>
              <div
                className="px-4 py-3 rounded-lg text-sm"
                style={{
                  background: "var(--bg-secondary)",
                  border: "1px solid var(--border)",
                  borderLeft: resolved ? (msg.confirmed ? "3px solid var(--success)" : "3px solid var(--danger)") : "3px solid var(--warning)",
                }}
              >
                <div className="flex items-center gap-2 mb-1.5">
                  <span style={{ color: "var(--warning)", fontSize: "14px" }}>⚠</span>
                  <span className="font-medium" style={{ color: "var(--text-primary)" }}>
                    {msg.tool_name || "Tool"} requires permission
                  </span>
                  {resolved && (
                    <span style={{ color: msg.confirmed ? "var(--success)" : "var(--danger)", fontSize: "12px" }}>
                      {msg.confirmed ? "— Allowed" : "— Denied"}
                    </span>
                  )}
                </div>
                {msg.args_summary && (
                  <pre
                    className="text-xs mb-2 whitespace-pre-wrap break-all"
                    style={{ color: "var(--text-secondary)", fontFamily: "'SF Mono', monospace", fontSize: "11px" }}
                  >
                    {msg.args_summary}
                  </pre>
                )}
                {!resolved && onToolConfirm && (
                  <div className="flex gap-2">
                    <button
                      onClick={() => onToolConfirm(msg.confirm_id!, true)}
                      className="px-3 py-1.5 rounded text-xs font-medium"
                      style={{ background: "var(--success-bg)", color: "var(--success)" }}
                    >
                      ✓ Allow
                    </button>
                    <button
                      onClick={() => onToolConfirm(msg.confirm_id!, false)}
                      className="px-3 py-1.5 rounded text-xs font-medium"
                      style={{ background: "var(--danger-bg)", color: "var(--danger)" }}
                    >
                      ✗ Deny
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
            <div key={msg.id} className="mb-3" style={{ marginLeft: "12px" }}>
              <div
                className="px-4 py-3 rounded-lg text-sm"
                style={{
                  background: "var(--bg-secondary)",
                  border: "1px solid var(--border)",
                  borderLeft: resolved ? "3px solid var(--success)" : "3px solid var(--accent)",
                }}
              >
                <div className="flex items-center gap-2 mb-1.5">
                  <span style={{ color: "var(--accent)", fontSize: "14px" }}>💬</span>
                  <span className="font-medium" style={{ color: "var(--text-primary)" }}>
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
                  <div className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>
                    → {msg.content}
                  </div>
                )}
              </div>
            </div>
          );
        }

        if (msg.role === "sub_agent") {
          const completed = msg.sub_agent_elapsed !== undefined;
          const agentIcon = AGENT_ICONS[msg.sub_agent_name || ""] || "🤖";
          const isActive = resolvedSubAgentId === msg.sub_agent_id;
          return (
            <button
              key={msg.id}
              onClick={() => { if (isActive) closeSubAgent(); else setActiveSubAgentId(msg.sub_agent_id ?? msg.id); }}
              className="mb-3 flex items-center gap-2 cursor-pointer py-1.5 px-3 rounded-md text-xs select-none transition-colors"
              style={{
                marginLeft: "12px",
                background: isActive ? "var(--accent-2-bg)" : "var(--bg-secondary)",
                border: `1px solid ${isActive ? "var(--accent-2)" : "var(--border)"}`,
                color: "var(--text-secondary)",
              }}
            >
              <span style={{ fontSize: "11px" }}>{agentIcon}</span>
              <span className="font-medium" style={{ color: "#c4b5fd" }}>{msg.sub_agent_display || msg.sub_agent_name}</span>
              {completed ? (
                <span className="ml-1" style={{ color: "var(--success)", fontFamily: "monospace" }}>✓</span>
              ) : (
                <span className="ml-1 animate-spin inline-block" style={{ color: "var(--accent-2)", fontFamily: "monospace", fontSize: "10px" }}>⟳</span>
              )}
              {completed && (
                <span style={{ color: "var(--text-secondary)", fontSize: "10px" }}>
                  {msg.sub_agent_iterations} steps · {msg.sub_agent_elapsed}s · {msg.sub_agent_tokens} tokens
                </span>
              )}
              {!completed && (
                <span className="animate-pulse" style={{ color: "var(--accent-2)", fontSize: "10px" }}>running...</span>
              )}
            </button>
          );
        }

        if (msg.role === "error") {
          return (
            <div key={msg.id} className="mb-3">
              <div
                className="px-4 py-3 rounded-lg text-sm"
                style={{ background: "var(--danger-bg)", border: "1px solid var(--danger-border)", color: "var(--danger)" }}
              >
                ⚠ {msg.content}
              </div>
            </div>
          );
        }

        if (msg.role === "screenshot") {
          return (
            <div key={msg.id} className="mb-3" style={{ marginLeft: "12px" }}>
              {msg.images && msg.images.length > 0 && msg.images.map((img, i) => (
                <img
                  key={i}
                  src={img}
                  alt="Browser screenshot"
                  className="max-w-full max-h-[400px] rounded-lg object-contain cursor-pointer border"
                  style={{ borderColor: "var(--border)" }}
                  onClick={() => setPreviewImage(img)}
                />
              ))}
            </div>
          );
        }

        const isUser = msg.role === "user";

        return (
          <div key={msg.id} className={`mb-4 group/msg relative ${isUser ? "flex justify-end" : ""}`}>
            <div
              className={`max-w-[85%] text-sm leading-relaxed ${
                isUser ? "px-4 py-2.5 rounded-2xl rounded-br-md" : "px-1 py-1"
              }`}
              style={{
                background: isUser ? "var(--accent)" : "transparent",
                color: isUser ? "var(--text-on-accent)" : "var(--text-primary)",
              }}
            >
              {msg.reasoning_content && (
                <details className="mb-2">
                  <summary
                    className="cursor-pointer text-xs py-1 px-2 rounded select-none"
                    style={{ color: "var(--text-secondary)", background: "var(--bg-tertiary)" }}
                  >
                    💭 Thinking
                  </summary>
                  <div
                    className="mt-1 p-2 rounded text-xs"
                    style={{ background: "var(--bg-tertiary)", borderLeft: "3px solid var(--accent-2)", color: "var(--text-secondary)" }}
                  >
                    <pre className="whitespace-pre-wrap" style={{ fontFamily: "'SF Mono', monospace", fontSize: "12px" }}>
                      {msg.reasoning_content}
                    </pre>
                  </div>
                </details>
              )}
              {isUser ? (
                <>
                  {msg.images && msg.images.length > 0 && (
                    <div className="flex gap-2 mb-2 flex-wrap">
                      {msg.images.map((img, i) => (
                        <img key={i} src={img} className="max-w-[200px] max-h-[200px] rounded-lg cursor-pointer object-contain" onClick={() => setPreviewImage(img)} />
                      ))}
                    </div>
                  )}
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                </>
              ) : (
                <div
                  className="prose prose-invert prose-sm max-w-none
                    [&_p]:my-2 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0
                    [&_h1]:text-base [&_h1]:font-bold [&_h1]:mt-4 [&_h1]:mb-2 [&_h1]:text-white
                    [&_h2]:text-sm [&_h2]:font-bold [&_h2]:mt-3 [&_h2]:mb-1.5 [&_h2]:text-white
                    [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:mt-2 [&_h3]:mb-1 [&_h3]:text-white
                    [&_ul]:my-1.5 [&_ul]:pl-5 [&_ol]:my-1.5 [&_ol]:pl-5
                    [&_li]:my-0.5
                    [&_pre]:my-2 [&_pre]:rounded-lg [&_pre]:overflow-hidden
                    [&_code]:text-[13px]
                    [&_a]:text-blue-400 [&_a]:no-underline [&_a:hover]:underline
                    [&_blockquote]:border-l-2 [&_blockquote]:border-gray-600 [&_blockquote]:pl-3 [&_blockquote]:text-gray-400
                    [&_strong]:text-white [&_em]:text-gray-300
                    [&_hr]:border-gray-700 [&_hr]:my-3
                    [&_table]:text-xs [&_th]:px-2 [&_th]:py-1 [&_td]:px-2 [&_td]:py-1 [&_th]:bg-[var(--bg-tertiary)]
                  "
                >
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      a: ({ children, ...props }: any) => (
                        <a {...props} target="_blank" rel="noopener noreferrer">{children}</a>
                      ),
                    }}
                  >{msg.content}</ReactMarkdown>
                </div>
              )}
            </div>
            {onBranch && !replaying && !msg.isStreaming && msg.id.startsWith("db-") && msg.role === "user" && (
              <button
                onClick={() => onBranch(msg.id)}
                title="Branch from here"
                className="absolute top-0 right-0 opacity-0 group-hover/msg:opacity-100 transition-opacity text-xs px-1.5 py-0.5 rounded"
                style={{
                  color: "var(--text-secondary)",
                  background: "var(--bg-secondary)",
                  border: "1px solid var(--border)",
                }}
              >
                ⎇ Branch
              </button>
            )}
          </div>
        );
      })}
      <div ref={bottomRef} />
      {previewImage && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: "rgba(0,0,0,0.85)" }}
          onClick={() => setPreviewImage(null)}
        >
          <img
            src={previewImage}
            alt="Preview"
            className="max-w-[90vw] max-h-[90vh] object-contain rounded-lg"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
      {resolvedSubAgentId && (() => {
        const agent = messages.find(m => m.sub_agent_id === resolvedSubAgentId || m.id === resolvedSubAgentId);
        if (!agent) return null;
        const completed = agent.sub_agent_elapsed !== undefined;
        const agentIcon = AGENT_ICONS[agent.sub_agent_name || ""] || "🤖";
        return (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center"
            style={{ background: "rgba(0,0,0,0.6)" }}
            onClick={closeSubAgent}
          >
            <div
              className="flex flex-col rounded-xl overflow-hidden"
              style={{
                background: "#1a1a2e",
                border: "1px solid var(--accent-2)",
                width: "min(680px, 90vw)",
                maxHeight: "80vh",
                boxShadow: "0 20px 60px rgba(0,0,0,0.5), 0 0 0 1px rgba(124,58,237,0.3)",
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <div
                className="flex items-center gap-2 px-4 py-3 select-none shrink-0"
                style={{ borderBottom: "1px solid var(--accent-2-bg)", background: "#16162a" }}
              >
                <span style={{ fontSize: "14px" }}>{agentIcon}</span>
                <span className="font-medium text-sm" style={{ color: "#d8b4fe" }}>
                  {agent.sub_agent_display || agent.sub_agent_name}
                </span>
                {!completed && (
                  <span className="flex items-center gap-1.5 ml-2">
                    <span className="animate-spin inline-block" style={{ color: "var(--accent-2)", fontSize: "11px" }}>⟳</span>
                    <span className="animate-pulse text-xs" style={{ color: "var(--accent-2)" }}>running...</span>
                  </span>
                )}
                {completed && (
                  <span className="text-xs ml-2" style={{ color: "var(--text-secondary)" }}>
                    ✓ {agent.sub_agent_iterations} steps · {agent.sub_agent_elapsed}s · {agent.sub_agent_tokens} tokens
                  </span>
                )}
                <button
                  onClick={closeSubAgent}
                  className="ml-auto text-sm px-2 py-0.5 rounded hover:opacity-80"
                  style={{ color: "var(--text-secondary)" }}
                >
                  ✕
                </button>
              </div>
              <div className="flex-1 overflow-y-auto px-4 py-4" style={{ background: "#131325" }}>
                {(() => {
                  const segments = parseSubAgentContent(modalContent);
                  if (segments.length === 0) {
                    return (
                      <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
                        (working...)
                      </span>
                    );
                  }
                  return (
                    <div className="flex flex-col gap-3">
                      {segments.map((seg, i) => {
                        if (seg.type === "text") {
                          return (
                            <div
                              key={i}
                              className="text-sm whitespace-pre-wrap leading-relaxed"
                              style={{ color: "var(--text-primary)" }}
                            >
                              {seg.content}
                            </div>
                          );
                        }
                        if (seg.type === "tool_call") {
                          return (
                            <div
                              key={i}
                              className="flex items-center gap-2 py-1.5 px-3 rounded-md text-xs select-none"
                              style={{
                                background: "#1e1b2e",
                                border: "1px solid var(--accent-2-bg)",
                                color: "var(--text-secondary)",
                              }}
                            >
                              <span style={{ color: "var(--accent-2)", fontFamily: "monospace", fontSize: "11px" }}>⚡</span>
                              <span className="font-medium" style={{ color: "#c4b5fd" }}>{seg.name}</span>
                              <span style={{ color: "var(--text-secondary)", fontFamily: "monospace" }}>{seg.content}</span>
                            </div>
                          );
                        }
                        if (seg.type === "tool_result") {
                          return (
                            <div
                              key={i}
                              className="rounded-md overflow-hidden"
                              style={{
                                borderLeft: "3px solid var(--success)",
                                background: "#1a1f1e",
                              }}
                            >
                              <div className="px-3 py-1.5 text-[10px] font-medium" style={{ color: "var(--success)", borderBottom: "1px solid var(--success-border)" }}>
                                ← {seg.name}
                              </div>
                              <pre
                                className="px-3 py-2 text-xs whitespace-pre-wrap break-all leading-relaxed"
                                style={{
                                  color: "var(--text-primary)",
                                  fontFamily: "'SF Mono', 'Fira Code', monospace",
                                  fontSize: "12px",
                                  maxHeight: "200px",
                                  overflow: "auto",
                                }}
                              >
                                {seg.content}
                              </pre>
                            </div>
                          );
                        }
                        return null;
                      })}
                    </div>
                  );
                })()}
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
});

ChatPanel.displayName = "ChatPanel";
export default ChatPanel;

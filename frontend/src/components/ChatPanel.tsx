import { forwardRef, useState } from "react";
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
}

interface Props {
  messages: ChatMessage[];
  connected: boolean;
  onToolConfirm?: (confirmId: string, approved: boolean) => void;
  onUserInput?: (inputId: string, answer: string) => void;
  onBranch?: (messageId: string) => void;
  replaying?: boolean;
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
  const accentColor = isMcp ? "#a78bfa" : "var(--accent)";
  const borderColor = isMcp ? "#7c3aed" : "var(--accent)";

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
          style={{ background: "var(--accent)", color: "#fff" }}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}

const ChatPanel = forwardRef<HTMLDivElement, Props>(({ messages, connected, onToolConfirm, onUserInput, onBranch, replaying }, bottomRef) => {
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
                <span className="font-medium" style={{ color: meta.isMcp ? "#c4b5fd" : "#67e8f9" }}>{meta.displayName}</span>
                {meta.serverLabel && (
                  <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: "#2d1f5e", color: "#a78bfa", fontSize: "10px" }}>
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
                  borderLeft: "3px solid #8b5cf6",
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
                <span className="font-medium" style={{ color: meta.isMcp ? "#c4b5fd" : "#67e8f9" }}>{meta.displayName}</span>
                {meta.serverLabel && (
                  <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: "#2d1f5e", color: "#a78bfa", fontSize: "10px" }}>
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
                <span style={{ color: "#34d399" }}>✓</span>
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
                  color: "#fbbf24",
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
                  borderLeft: resolved ? (msg.confirmed ? "3px solid #34d399" : "3px solid #f87171") : "3px solid #fbbf24",
                }}
              >
                <div className="flex items-center gap-2 mb-1.5">
                  <span style={{ color: "#fbbf24", fontSize: "14px" }}>⚠</span>
                  <span className="font-medium" style={{ color: "var(--text-primary)" }}>
                    {msg.tool_name || "Tool"} requires permission
                  </span>
                  {resolved && (
                    <span style={{ color: msg.confirmed ? "#34d399" : "#f87171", fontSize: "12px" }}>
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
                      style={{ background: "#065f46", color: "#34d399" }}
                    >
                      ✓ Allow
                    </button>
                    <button
                      onClick={() => onToolConfirm(msg.confirm_id!, false)}
                      className="px-3 py-1.5 rounded text-xs font-medium"
                      style={{ background: "#7f1d1d", color: "#f87171" }}
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
                  borderLeft: resolved ? "3px solid #34d399" : "3px solid #60a5fa",
                }}
              >
                <div className="flex items-center gap-2 mb-1.5">
                  <span style={{ color: "#60a5fa", fontSize: "14px" }}>💬</span>
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

        if (msg.role === "error") {
          return (
            <div key={msg.id} className="mb-3">
              <div
                className="px-4 py-3 rounded-lg text-sm"
                style={{ background: "#2d1215", border: "1px solid #5c1d22", color: "#fca5a5" }}
              >
                ⚠ {msg.content}
              </div>
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
                color: isUser ? "#fff" : "var(--text-primary)",
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
                    style={{ background: "var(--bg-tertiary)", borderLeft: "3px solid #8b5cf6", color: "var(--text-secondary)" }}
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
                        <img key={i} src={img} className="max-w-[200px] max-h-[200px] rounded-lg cursor-pointer object-contain" onClick={() => window.open(img, "_blank")} />
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
    </div>
  );
});

ChatPanel.displayName = "ChatPanel";
export default ChatPanel;

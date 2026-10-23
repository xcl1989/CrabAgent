/**
 * MobileTimeline — /m 会话实时时间线（屏 2）+ 会话级控制。
 *
 * 能力（P1.5）：
 * - 新建会话（可带工作空间）
 * - 切换工作空间 / 模型（provider+model）/ Agent
 * - 发送图片（base64 dataURL，≤5 张、单张 ≤5MB，与桌面端同参）
 * - assistant 消息 markdown 渲染（react-markdown + gfm + highlight）
 *
 * ⚠️ SSE 事件类型是线上小写格式（"text_delta"/"text_done"/"tool_call"），
 *    不是 Python EventType 枚举的大写名。text_delta 的 data.text 是增量
 *    chunk（追加），text_done 是完整全文（工具轮次为空串）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { listSessions, getMessages, sendPrompt, createSession, Message, Session } from "../../api/sessions";
import { listWorkspaces, WorkspaceInfo } from "../../api/sessions";
import { listProviders, getProviderModels, Provider } from "../../api/providers";
import { listAgentProfiles, AgentProfile } from "../../api/agents";
import { connectSSE } from "../../api/events";
import "./mobile.css";

interface LiveItem {
  id: string;
  kind: "text" | "tool" | "typing";
  text: string;
  streaming: boolean;
}

interface ModelOption {
  provider: string;
  providerLabel: string;
  model: string;
}

interface Props {
  sessionId: string | null;
  onSessionChange: (sessionId: string) => void;
}

let liveSeq = 0;
const nextLiveId = () => `live-${++liveSeq}`;

const MAX_IMAGES = 5;
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

export function MobileTimeline({ sessionId, onSessionChange }: Props) {
  const { t } = useTranslation();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [live, setLive] = useState<LiveItem[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [connected, setConnected] = useState(false);

  // ── 会话级选择（进入会话时从 session 初始化） ──
  const [selectedModel, setSelectedModel] = useState("");
  const [selectedProvider, setSelectedProvider] = useState("");
  const [selectedAgent, setSelectedAgent] = useState("");

  // ── 图片附件 ──
  const [pendingImages, setPendingImages] = useState<string[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── 底部弹层 ──
  const [sheet, setSheet] = useState<null | "workspace" | "model" | "agent">(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);
  const [currentWorkspace, setCurrentWorkspace] = useState("");
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
  const [agents, setAgents] = useState<AgentProfile[]>([]);
  const [creating, setCreating] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);

  // 会话列表 + 工作空间
  useEffect(() => {
    void listSessions().then((ss) => {
      setSessions(ss);
      if (!sessionId && ss.length > 0) onSessionChange(ss[0].session_id);
    }).catch(() => undefined);
    void listWorkspaces().then((ws) => {
      setWorkspaces(ws);
      const cur = ws.find((w) => w.workspace);
      // WorkspaceInfo 无 is_current 字段时默认第一项；新建会话可显式选择
      if (cur) setCurrentWorkspace(cur.workspace);
    }).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 切换会话时：拉历史 + 从 session 同步模型/agent 选择
  const refreshMessages = useCallback(async (sid: string) => {
    try {
      const msgs = await getMessages(sid, 80);
      setMessages(
        msgs.filter(
          (m) => (m.role === "user" || m.role === "assistant") && (m.content ?? "").trim() !== "",
        ),
      );
    } catch {
      setMessages([]);
    }
  }, []);

  useEffect(() => {
    setLive([]);
    setConnected(false);
    setPendingImages([]);
    if (!sessionId) return;
    void refreshMessages(sessionId);
    // 从 session 同步模型/agent（provider 信息不在 Session 里，留空走服务端默认）
    const s = sessions.find((x) => x.session_id === sessionId);
    setSelectedModel(s?.model ?? "");
    setSelectedProvider("");
    setSelectedAgent(s?.agent ?? "");
    if (s?.workspace) setCurrentWorkspace(s.workspace);

    const es = connectSSE(sessionId, (event) => {
      setConnected(true);
      const d = event.data as Record<string, unknown>;
      switch (event.type) {
        case "text_delta": {
          const chunk = (d.text as string) || "";
          if (!chunk) return;
          setLive((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.kind === "text" && last.streaming) {
              return [...prev.slice(0, -1), { ...last, text: last.text + chunk }];
            }
            return [...prev, { id: nextLiveId(), kind: "text", text: chunk, streaming: true }];
          });
          break;
        }
        case "text_done": {
          const fullText = (d.text as string) || "";
          void refreshMessages(sessionId).then(() => {
            setLive((prev) =>
              prev.filter((i) => {
                if (i.kind !== "text") return true;
                if (!i.streaming) return false;
                return fullText ? i.text !== fullText : false;
              }),
            );
          });
          break;
        }
        case "tool_call": {
          const name = (d.name as string) || "tool";
          setLive((prev) => [
            ...prev.filter((i) => i.kind !== "typing"),
            { id: nextLiveId(), kind: "tool", text: name, streaming: false },
            { id: "typing", kind: "typing", text: "", streaming: false },
          ]);
          break;
        }
        case "agent_end":
        case "agent_error": {
          setLive((prev) => prev.filter((i) => i.kind !== "typing"));
          if (sessionId) void refreshMessages(sessionId);
          break;
        }
        default:
          break;
      }
    });
    return () => {
      es.close();
      setConnected(false);
    };
    // sessions 变化时不重连 SSE，只影响同步选择 —— 从 ref 读取即可
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, refreshMessages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, live]);

  // ── 动作 ──

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if ((!text && pendingImages.length === 0) || !sessionId || sending) return;
    setSending(true);
    setInput("");
    const images = [...pendingImages];
    setPendingImages([]);
    try {
      await sendPrompt(
        sessionId,
        text || t("mobile.imagesOnly"),
        selectedModel || undefined,
        images.length > 0 ? images : undefined,
        selectedAgent || undefined,
        undefined,
        selectedProvider || undefined,
      );
      setTimeout(() => void refreshMessages(sessionId), 1200);
    } catch {
      // 发送失败：把图片还回去，避免丢失
      setPendingImages((prev) => [...images, ...prev]);
    } finally {
      setSending(false);
    }
  }, [input, sessionId, sending, pendingImages, selectedModel, selectedAgent, selectedProvider, refreshMessages, t]);

  const handleNewSession = useCallback(async () => {
    if (creating) return;
    setCreating(true);
    try {
      const s = await createSession(undefined, currentWorkspace || undefined);
      setSessions((prev) => [s, ...prev]);
      onSessionChange(s.session_id);
      setSheet(null);
    } catch {
      // 401 由 client 统一处理
    } finally {
      setCreating(false);
    }
  }, [creating, currentWorkspace, onSessionChange]);

  const processImageFile = useCallback((file: File) => {
    if (file.size > MAX_IMAGE_BYTES || !file.type.startsWith("image/")) return;
    setPendingImages((prev) => {
      if (prev.length >= MAX_IMAGES) return prev;
      const reader = new FileReader();
      reader.onload = (e) => {
        const dataUrl = e.target?.result as string;
        if (dataUrl) setPendingImages((p) => (p.length < MAX_IMAGES ? [...p, dataUrl] : p));
      };
      reader.readAsDataURL(file);
      return prev;
    });
  }, []);

  // ── 弹层数据懒加载 ──
  const openSheet = useCallback(async (which: "workspace" | "model" | "agent") => {
    setSheet(which);
    if (which === "model" && modelOptions.length === 0) {
      try {
        const providers: Provider[] = await listProviders();
        const enabled = providers.filter((p) => p.enabled);
        const lists = await Promise.allSettled(enabled.map((p) => getProviderModels(p.name)));
        const opts: ModelOption[] = [];
        lists.forEach((r, i) => {
          if (r.status !== "fulfilled") return;
          for (const m of r.value) {
            opts.push({
              provider: enabled[i].name,
              providerLabel: enabled[i].display_name || enabled[i].name,
              model: m.id,
            });
          }
        });
        setModelOptions(opts);
      } catch {
        setModelOptions([]);
      }
    }
    if (which === "agent" && agents.length === 0) {
      try {
        setAgents(await listAgentProfiles());
      } catch {
        setAgents([]);
      }
    }
  }, [modelOptions.length, agents.length]);

  const activeSession = useMemo(
    () => sessions.find((s) => s.session_id === sessionId),
    [sessions, sessionId],
  );
  const working = live.some((i) => i.kind === "typing");

  const agentLabel = useMemo(() => {
    if (selectedAgent) {
      const a = agents.find((x) => x.name === selectedAgent);
      return a?.display_name || a?.name || selectedAgent;
    }
    return activeSession?.agent || t("mobile.defaultAgent");
  }, [selectedAgent, agents, activeSession, t]);

  return (
    <div className="flex flex-col h-full relative">
      {/* 会话选择器 + 工具行 */}
      <div className="px-4 pt-2 pb-2 border-b border-zinc-800 bg-zinc-950/80 flex-shrink-0 flex flex-col gap-2">
        <div className="flex gap-2 items-center">
          <select
            value={sessionId ?? ""}
            onChange={(e) => onSessionChange(e.target.value)}
            className="flex-1 min-w-0 bg-zinc-900 border border-zinc-700 rounded-xl px-3 py-2 text-[13.5px] outline-none"
          >
            {sessions.length === 0 && <option value="">{t("mobile.noSessions")}</option>}
            {sessions.map((s) => (
              <option key={s.session_id} value={s.session_id}>
                {s.title || s.session_id.slice(0, 12)}
              </option>
            ))}
          </select>
          <button
            onClick={() => void handleNewSession()}
            disabled={creating}
            title={t("mobile.newChat")}
            className="w-9 h-9 flex-shrink-0 rounded-xl bg-blue-500/15 border border-blue-500/40 text-blue-400 text-[18px] leading-none active:bg-blue-500/30 disabled:opacity-40"
          >
            ＋
          </button>
        </div>
        <div className="flex gap-1.5 overflow-x-auto text-[11.5px]" style={{ scrollbarWidth: "none" }}>
          <button onClick={() => void openSheet("workspace")} className="chip whitespace-nowrap">
            🌐 {currentWorkspace ? currentWorkspace.split("/").pop() : t("mobile.workspace")}
          </button>
          <button onClick={() => void openSheet("model")} className="chip whitespace-nowrap">
            ⚙️ {selectedModel ? selectedModel.split("/").pop() : t("mobile.defaultModel")}
          </button>
          <button onClick={() => void openSheet("agent")} className="chip whitespace-nowrap">
            🤖 {agentLabel}
          </button>
        </div>
      </div>

      {/* 时间线 */}
      <div className="flex-1 overflow-y-auto px-4 pt-3 pb-4">
        {!sessionId && (
          <p className="text-[13px] text-zinc-600 mt-8 text-center">{t("mobile.noSessions")}</p>
        )}
        {sessionId && (
          <div className="flex flex-col gap-3">
            {messages.map((m) => (
              <div key={m.id} className={m.role === "user" ? "self-end max-w-[85%]" : "self-start max-w-[92%]"}>
                <div className="text-[10.5px] text-zinc-500 mb-0.5 font-semibold">
                  {m.role === "user" ? t("mobile.you") : "CrabAgent"}
                </div>
                <div
                  className={`rounded-2xl px-3.5 py-2.5 ${
                    m.role === "user"
                      ? "bg-purple-900/40 border border-purple-500/25 text-[13.5px] leading-relaxed whitespace-pre-wrap break-words"
                      : "bg-zinc-900/80 border border-zinc-800 mc-md"
                  }`}
                >
                  {m.role === "user" ? (
                    m.content
                  ) : (
                    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                      {m.content}
                    </ReactMarkdown>
                  )}
                </div>
                {/* 用户消息图片 */}
                {m.role === "user" && m.image_data && (
                  <img src={m.image_data} alt="" className="mt-1.5 rounded-xl max-h-40" />
                )}
              </div>
            ))}

            {/* 实时事件（尚未落库） */}
            {live.map((item) =>
              item.kind === "tool" ? (
                <div key={item.id} className="self-start text-[12px] text-sky-300/80 bg-sky-950/40 border border-sky-500/20 rounded-lg px-2.5 py-1.5">
                  🔧 {item.text}
                </div>
              ) : item.kind === "typing" ? (
                <div key={item.id} className="self-start flex gap-1.5 items-center px-1 py-2">
                  {[0, 1, 2].map((i) => (
                    <span
                      key={i}
                      className="w-1.5 h-1.5 rounded-full bg-zinc-500 animate-bounce"
                      style={{ animationDelay: `${i * 0.2}s` }}
                    />
                  ))}
                </div>
              ) : (
                <div key={item.id} className="self-start max-w-[92%]">
                  <div className="text-[10.5px] text-zinc-500 mb-0.5 font-semibold">CrabAgent</div>
                  <div className="rounded-2xl px-3.5 py-2.5 bg-zinc-900/80 border border-zinc-800 mc-md">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.text}</ReactMarkdown>
                  </div>
                </div>
              ),
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* 待发图片预览 */}
      {pendingImages.length > 0 && (
        <div className="flex-shrink-0 px-4 py-2 border-t border-zinc-800 bg-zinc-950/90 flex gap-2 overflow-x-auto">
          {pendingImages.map((img, i) => (
            <div key={i} className="relative flex-shrink-0">
              <img src={img} alt="" className="w-14 h-14 object-cover rounded-lg border border-zinc-700" />
              <button
                onClick={() => setPendingImages((prev) => prev.filter((_, j) => j !== i))}
                className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-red-500 text-white text-[11px] leading-none"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {/* 插话输入条 */}
      <div
        className="flex-shrink-0 border-t border-zinc-800 bg-zinc-950/90 backdrop-blur px-3 pt-2.5 flex gap-2 items-center"
        style={{ paddingBottom: "calc(0.625rem + env(safe-area-inset-bottom))" }}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          multiple
          className="hidden"
          onChange={(e) => {
            for (const f of Array.from(e.target.files ?? [])) processImageFile(f);
            e.target.value = "";
          }}
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={pendingImages.length >= MAX_IMAGES}
          className="w-9 h-9 flex-shrink-0 rounded-full bg-zinc-800/70 border border-zinc-700 text-zinc-400 text-[16px] disabled:opacity-40"
          title={t("mobile.attachImage")}
        >
          🖼
        </button>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && void handleSend()}
          placeholder={working ? t("mobile.steerPlaceholder") : t("mobile.inputPlaceholder")}
          className="flex-1 min-w-0 bg-zinc-900 border border-zinc-700 rounded-full px-4 py-2.5 text-[13.5px] outline-none focus:border-blue-500/60"
        />
        <button
          onClick={() => void handleSend()}
          disabled={(!input.trim() && pendingImages.length === 0) || sending || !sessionId}
          className="w-10 h-10 flex-shrink-0 rounded-full bg-green-500 text-black text-[16px] font-bold disabled:opacity-30 active:scale-95 flex items-center justify-center"
        >
          ➤
        </button>
      </div>

      {/* 连接状态提示 */}
      {!connected && sessionId && (
        <div className="absolute top-0 left-0 right-0 bg-red-500/10 border-b border-red-500/30 text-red-400 text-[12px] px-4 py-2 z-20">
          {t("mobile.reconnecting")}
        </div>
      )}

      {/* ── 底部弹层：工作空间 / 模型 / Agent ── */}
      {sheet && (
        <div className="mc-sheet-backdrop" onClick={() => setSheet(null)}>
          <div className="mc-sheet" onClick={(e) => e.stopPropagation()}>
            <div className="px-4 pt-3 pb-2 text-[14px] font-semibold border-b border-zinc-800 flex items-center justify-between">
              <span>
                {sheet === "workspace"
                  ? t("mobile.workspace")
                  : sheet === "model"
                    ? t("mobile.selectModel")
                    : t("mobile.selectAgent")}
              </span>
              <button onClick={() => setSheet(null)} className="text-zinc-500 text-[13px]">
                ✕
              </button>
            </div>
            <div className="overflow-y-auto px-3 py-2 pb-6">
              {sheet === "workspace" && (
                <>
                  {workspaces.map((w) => (
                    <button
                      key={w.workspace}
                      onClick={() => {
                        setCurrentWorkspace(w.workspace);
                        setSheet(null);
                      }}
                      className={`w-full text-left px-3 py-2.5 rounded-xl text-[13.5px] mb-1 flex justify-between items-center ${
                        w.workspace === currentWorkspace
                          ? "bg-blue-500/15 text-blue-300"
                          : "text-zinc-300 active:bg-zinc-800"
                      }`}
                    >
                      <span className="truncate">{w.workspace}</span>
                      {w.workspace === currentWorkspace && <span>✓</span>}
                    </button>
                  ))}
                  <p className="text-[11px] text-zinc-600 px-3 mt-2">{t("mobile.workspaceHint")}</p>
                </>
              )}
              {sheet === "model" && (
                <>
                  <button
                    onClick={() => {
                      setSelectedModel("");
                      setSelectedProvider("");
                      setSheet(null);
                    }}
                    className={`w-full text-left px-3 py-2.5 rounded-xl text-[13.5px] mb-1 ${
                      !selectedModel ? "bg-blue-500/15 text-blue-300" : "text-zinc-300 active:bg-zinc-800"
                    }`}
                  >
                    {t("mobile.defaultModel")}
                  </button>
                  {modelOptions.map((o) => {
                    const val = o.model;
                    const active = selectedModel === val && selectedProvider === o.provider;
                    return (
                      <button
                        key={`${o.provider}/${o.model}`}
                        onClick={() => {
                          setSelectedModel(val);
                          setSelectedProvider(o.provider);
                          setSheet(null);
                        }}
                        className={`w-full text-left px-3 py-2.5 rounded-xl text-[13.5px] mb-1 flex justify-between items-center gap-2 ${
                          active ? "bg-blue-500/15 text-blue-300" : "text-zinc-300 active:bg-zinc-800"
                        }`}
                      >
                        <span className="truncate">{o.model}</span>
                        <span className="text-[10.5px] text-zinc-500 flex-shrink-0">{o.providerLabel}</span>
                      </button>
                    );
                  })}
                  {modelOptions.length === 0 && (
                    <p className="text-[12px] text-zinc-600 px-3 py-2">{t("mobile.loading")}</p>
                  )}
                </>
              )}
              {sheet === "agent" && (
                <>
                  <button
                    onClick={() => {
                      setSelectedAgent("");
                      setSheet(null);
                    }}
                    className={`w-full text-left px-3 py-2.5 rounded-xl text-[13.5px] mb-1 ${
                      !selectedAgent ? "bg-blue-500/15 text-blue-300" : "text-zinc-300 active:bg-zinc-800"
                    }`}
                  >
                    {t("mobile.defaultAgent")}
                  </button>
                  {agents.map((a) => (
                    <button
                      key={a.name}
                      onClick={() => {
                        setSelectedAgent(a.name);
                        setSheet(null);
                      }}
                      className={`w-full text-left px-3 py-2.5 rounded-xl text-[13.5px] mb-1 flex justify-between items-center gap-2 ${
                        selectedAgent === a.name ? "bg-blue-500/15 text-blue-300" : "text-zinc-300 active:bg-zinc-800"
                      }`}
                    >
                      <span className="truncate">{a.display_name || a.name}</span>
                      <span className="text-[10.5px] text-zinc-500 flex-shrink-0">{a.name}</span>
                    </button>
                  ))}
                  {agents.length === 0 && (
                    <p className="text-[12px] text-zinc-600 px-3 py-2">{t("mobile.loading")}</p>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

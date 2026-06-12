import { useState, useEffect, useCallback, useRef } from "react";
import {
  Smartphone,
  QrCode,
  LogOut,
  Send,
  RefreshCw,
  Bell,
  MessageSquare,
  FolderOpen,
  ExternalLink,
  Check,
  AlertCircle,
  ChevronDown,
} from "lucide-react";
import { Button } from "./ui";
import { toast } from "./ui/Toast";
import * as wechatApi from "../api/wechat";
import type { WeChatStatus, WeChatConversation } from "../api/wechat";
import WorkspaceSwitcher from "./WorkspaceSwitcher";

export default function WeChatPanel() {
  const [status, setStatus] = useState<WeChatStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [qrImage, setQrImage] = useState<string>("");
  const [qrUrl, setQrUrl] = useState<string>("");
  const [qrPolling, setQrPolling] = useState(false);
  const [qrError, setQrError] = useState("");
  const [testing, setTesting] = useState(false);
  const [conversations, setConversations] = useState<WeChatConversation[]>([]);
  const [convsLoading, setConvsLoading] = useState(false);
  const [showConversations, setShowConversations] = useState(false);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const s = await wechatApi.getStatus();
      setStatus(s);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchConversations = useCallback(async () => {
    setConvsLoading(true);
    try {
      const convs = await wechatApi.getConversations();
      setConversations(convs);
    } catch {
      // ignore
    } finally {
      setConvsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, [fetchStatus]);

  // ---- QR Login ----

  const handleStartLogin = async () => {
    setQrError("");
    setQrImage("");
    setQrUrl("");
    try {
      const result = await wechatApi.startQRLogin();
      if (result.qrcode_img_base64) {
        setQrImage(`data:image/png;base64,${result.qrcode_img_base64}`);
      } else if (result.qrcode_url) {
        setQrUrl(result.qrcode_url);
      } else {
        setQrError("未能获取二维码，请检查网络连接");
      }
      // Start polling
      setQrPolling(true);
      pollTimerRef.current = setInterval(async () => {
        try {
          const pollResult = await wechatApi.pollQRStatus();
          if (pollResult.status === "confirmed" && pollResult.logged_in) {
            setQrPolling(false);
            setQrImage("");
            setQrUrl("");
            if (pollTimerRef.current) clearInterval(pollTimerRef.current);
            toast.success("微信绑定成功！");
            await fetchStatus();
          } else if (pollResult.status === "expired") {
            setQrPolling(false);
            setQrImage("");
            setQrUrl("");
            setQrError("二维码已过期，请重新扫码");
            if (pollTimerRef.current) clearInterval(pollTimerRef.current);
          } else if (pollResult.status === "scanned") {
            setQrError("已扫描，请在手机上确认登录");
          }
        } catch {
          // Polling error — keep trying
        }
      }, 2000);
    } catch (e: unknown) {
      setQrError(e instanceof Error ? e.message : "获取二维码失败");
    }
  };

  const handleLogout = async () => {
    try {
      await wechatApi.logout();
      toast.success("已退出微信登录");
      await fetchStatus();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "操作失败");
    }
  };

  // ---- Config toggles ----

  const toggleConfig = async (key: keyof WeChatStatus, value: boolean) => {
    try {
      await wechatApi.updateConfig({ [key]: value } as Record<string, unknown>);
      await fetchStatus();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    }
  };

  const handleWorkspaceChange = async (ws: string) => {
    try {
      await wechatApi.updateConfig({ workspace: ws });
      await fetchStatus();
      toast.success("工作空间已更新");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    }
  };

  const handleTestMessage = async () => {
    setTesting(true);
    try {
      await wechatApi.sendTestMessage("Hello from CrabAgent! 🦀");
      toast.success("测试消息已发送");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "发送失败");
    } finally {
      setTesting(false);
    }
  };

  // Load conversations when logged in
  useEffect(() => {
    if (status?.logged_in) {
      fetchConversations();
    }
  }, [status?.logged_in, fetchConversations]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <RefreshCw size={16} className="animate-spin text-[var(--text-tertiary)]" />
      </div>
    );
  }

  const loggedIn = status?.logged_in ?? false;

  return (
    <div className="space-y-4">
      {/* ── Card 1: Account ── */}
      <div className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5">
        <div className="flex items-center gap-2 mb-4">
          <Smartphone size={16} className="text-[var(--brand)]" />
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">账号</h3>
        </div>

        {/* Binding status */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div
              className={`w-2.5 h-2.5 rounded-full ${
                loggedIn ? "bg-green-500" : "bg-gray-400"
              }`}
            />
            <span className="text-sm text-[var(--text-secondary)]">
              {loggedIn
                ? `已绑定 ${status?.account_id ? `(${status.account_id})` : ""}`
                : "未绑定"}
            </span>
          </div>
          {loggedIn ? (
            <Button variant="secondary" size="sm" onClick={handleLogout}>
              <LogOut size={14} />
              退出登录
            </Button>
          ) : (
            <Button variant="brand" size="sm" onClick={handleStartLogin} disabled={qrPolling}>
              <QrCode size={14} />
              {qrPolling ? "等待扫码..." : "扫码绑定"}
            </Button>
          )}
        </div>

        {/* QR Code Display */}
        {(qrImage || qrUrl) && (
          <div className="mt-4 flex flex-col items-center gap-3 p-4 bg-[var(--bg-primary)] rounded-lg">
            {qrImage ? (
              <img src={qrImage} alt="QR Code" className="w-48 h-48" />
            ) : (
              <div className="w-48 h-48 flex flex-col items-center justify-center bg-white rounded-lg p-3">
                <img
                  src={`https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=${encodeURIComponent(qrUrl)}`}
                  alt="QR Code"
                  className="w-40 h-40"
                />
              </div>
            )}
            <p className="text-xs text-[var(--text-tertiary)]">
              请用微信扫描二维码绑定
            </p>
            {qrUrl && (
              <a
                href={qrUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-[var(--brand)] hover:underline"
              >
                或点击此处打开链接
              </a>
            )}
          </div>
        )}

        {qrError && (
          <p className="mt-3 text-xs text-orange-500">{qrError}</p>
        )}

        {/* Workspace + Auto-reply + Test (only when logged in) */}
        {loggedIn && (
          <>
            <div className="mt-4 pt-4 border-t border-[var(--border)]">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 flex-1 mr-3">
                  <FolderOpen size={14} className="text-[var(--text-tertiary)] shrink-0" />
                  <span className="text-xs text-[var(--text-secondary)]">工作空间</span>
                </div>
                <WorkspaceSwitcher
                  current={status?.workspace ?? ""}
                  onChange={handleWorkspaceChange}
                />
              </div>
            </div>

            <div className="mt-3 pt-3 border-t border-[var(--border)]">
              <ToggleRow
                label="自动回复"
                desc="收到微信消息时自动通过 Agent 处理并回复"
                checked={status?.auto_reply ?? false}
                onChange={(v) => toggleConfig("auto_reply", v)}
              />
            </div>

            <div className="flex gap-2 mt-3 pt-3 border-t border-[var(--border)]">
              <Button
                variant="secondary"
                size="sm"
                onClick={handleTestMessage}
                disabled={testing}
              >
                {testing ? (
                  <RefreshCw size={14} className="animate-spin" />
                ) : (
                  <Send size={14} />
                )}
                发送测试消息
              </Button>
            </div>
          </>
        )}
      </div>

      {/* ── Card 2: Notifications ── */}
      {loggedIn && (
        <div className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3">
            <Bell size={16} className="text-[var(--brand)]" />
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">通知</h3>
          </div>

          <div className="space-y-0.5">
            <ToggleRow
              label="任务逾期通知"
              desc="任务超过截止时间时推送提醒"
              checked={status?.notify_task_overdue ?? false}
              onChange={(v) => toggleConfig("notify_task_overdue", v)}
            />
            <ToggleRow
              label="定时任务完成通知"
              desc="定时任务执行完成后推送结果"
              checked={status?.notify_schedule_result ?? false}
              onChange={(v) => toggleConfig("notify_schedule_result", v)}
            />
            <ToggleRow
              label="邮件摘要推送"
              desc="将邮件摘要同步推送到微信"
              checked={status?.notify_email_summary ?? false}
              onChange={(v) => toggleConfig("notify_email_summary", v)}
            />
          </div>

          {/* Push target status */}
          <div className="mt-3 pt-3 border-t border-[var(--border)]">
            {status?.notify_target_user ? (
              <div className="flex items-center gap-1.5 text-xs text-[var(--success)]">
                <Check size={12} />
                <span>推送目标已设置</span>
              </div>
            ) : (
              <div className="flex items-start gap-1.5 text-xs text-[var(--text-tertiary)]">
                <AlertCircle size={12} className="shrink-0 mt-0.5" />
                <span>
                  推送目标未设置。请先通过微信给 Bot 发送一条消息，
                  系统会自动记录推送目标。
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Card 3: Conversation History (collapsible) ── */}
      {loggedIn && (
        <div className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5">
          <button
            onClick={() => setShowConversations(!showConversations)}
            className="w-full flex items-center justify-between"
          >
            <div className="flex items-center gap-2">
              <MessageSquare size={16} className="text-[var(--brand)]" />
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">会话记录</h3>
              {conversations.length > 0 && (
                <span className="text-[10px] text-[var(--text-tertiary)] bg-[var(--bg-tertiary)] px-1.5 py-0.5 rounded-full">
                  {conversations.length}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  fetchConversations();
                }}
                disabled={convsLoading}
              >
                <RefreshCw size={12} className={convsLoading ? "animate-spin" : ""} />
              </Button>
              <ChevronDown
                size={14}
                className={`text-[var(--text-tertiary)] transition-transform ${showConversations ? "rotate-180" : ""}`}
              />
            </div>
          </button>

          {showConversations && (
            <div className="mt-3">
              {conversations.length === 0 ? (
                <p className="text-xs text-[var(--text-tertiary)] py-3 text-center">
                  暂无微信会话记录
                </p>
              ) : (
                <div className="space-y-2">
                  {conversations.map((conv) => {
                    const name = conv.title.replace(/^微信\s*-\s*/, "");
                    const wsName = conv.workspace ? conv.workspace.split("/").pop() : "";
                    return (
                      <a
                        key={conv.session_id}
                        href={`/#/chat/${conv.session_id}`}
                        className="flex items-center gap-3 p-3 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)] hover:border-[var(--brand)] transition-colors cursor-pointer group"
                      >
                        <div className="w-8 h-8 rounded-full bg-[var(--brand)]/10 flex items-center justify-center shrink-0">
                          <Smartphone size={14} className="text-[var(--brand)]" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium text-[var(--text-primary)] truncate">
                              {name}
                            </span>
                            {wsName && (
                              <span className="text-[10px] text-[var(--text-tertiary)] bg-[var(--bg-tertiary)] px-1.5 py-0.5 rounded shrink-0">
                                {wsName}
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-[var(--text-tertiary)] truncate mt-0.5">
                            {conv.last_message || "(无消息)"}
                          </p>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <span className="text-[10px] text-[var(--text-tertiary)]">
                            {conv.message_count} 条
                          </span>
                          <ExternalLink
                            size={12}
                            className="text-[var(--text-tertiary)] opacity-0 group-hover:opacity-100 transition-opacity"
                          />
                        </div>
                      </a>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---- Toggle Row Component ----

function ToggleRow({
  label,
  desc,
  checked,
  onChange,
}: {
  label: string;
  desc: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between py-2.5">
      <div className="flex-1 mr-4">
        <p className="text-sm text-[var(--text-primary)]">{label}</p>
        <p className="text-xs text-[var(--text-tertiary)] mt-0.5">{desc}</p>
      </div>
      <button
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
          checked
            ? "bg-[var(--brand)]"
            : "bg-[var(--border)]"
        }`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
            checked ? "translate-x-6" : "translate-x-1"
          }`}
        />
      </button>
    </div>
  );
}

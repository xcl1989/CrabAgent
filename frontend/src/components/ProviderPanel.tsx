import { useTranslation } from "react-i18next";
import { useState, useEffect, useRef } from "react";
import { Plus, Trash2, Star, StarOff, ChevronDown, ChevronRight, X, Check, ExternalLink, Loader2 } from "lucide-react";
import { Provider, CatalogEntry } from "../api/providers";
import * as providersApi from "../api/providers";
import * as chatgptApi from "../api/chatgpt";

/** Format a duration in seconds to a human-readable window label. */
function formatWindow(seconds: number | null | undefined): string {
  if (!seconds) return "";
  if (seconds >= 86400) return `${Math.round(seconds / 86400)} 天窗口`;
  if (seconds >= 3600) return `${Math.round(seconds / 3600)} 小时窗口`;
  return `${Math.round(seconds / 60)} 分钟窗口`;
}

/** Format remaining time before reset. */
function formatReset(seconds: number | null | undefined): string {
  if (!seconds) return "";
  if (seconds >= 86400) return `${(seconds / 86400).toFixed(1)} 天后重置`;
  if (seconds >= 3600) return `${(seconds / 3600).toFixed(1)} 小时后重置`;
  return `${Math.round(seconds / 60)} 分钟后重置`;
}
import * as quotaApi from "../api/quota";
import { Modal, Button, Input, PasswordInput, ConfirmDialog, EmptyState } from "./ui";
import { toast } from "./ui/Toast";
import { cn } from "../lib/cn";
import { emitProvidersChanged } from "../lib/providerSync";

interface Props {
  providers: Provider[];
  catalog: CatalogEntry[];
  onClose: () => void;
  onRefresh: () => void;
}

export default function ProviderPanel({
  providers,
  catalog,
  onClose,
  onRefresh,
}: Props) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<"list" | "add">("list");
  const [formType, setFormType] = useState(catalog[0]?.type || "");
  const [formVariantId, setFormVariantId] = useState<string>("");
  const [formName, setFormName] = useState("");
  const [formKey, setFormKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [expandedProvider, setExpandedProvider] = useState<string | null>(null);
  const [newModelInput, setNewModelInput] = useState<Record<string, string>>({});
  const [modelBusy, setModelBusy] = useState<string | null>(null);
  const [proxyInput, setProxyInput] = useState<Record<string, string>>({});
  const [proxyBusy, setProxyBusy] = useState<string | null>(null);
  const [chatgptAuth, setChatgptAuth] = useState<chatgptApi.ChatGPTAuthStatus | null>(null);
  const [chatgptDeviceCode, setChatgptDeviceCode] = useState<chatgptApi.DeviceCodeInfo | null>(null);
  const [chatgptBusy, setChatgptBusy] = useState(false);
  const [chatgptPolling, setChatgptPolling] = useState(false);
  const [chatgptAccount, setChatgptAccount] = useState<chatgptApi.ChatGPTAccountInfo | null>(null);
  const [chatgptAccountBusy, setChatgptAccountBusy] = useState(false);
  const [resetBusy, setResetBusy] = useState(false);
  const [resetConfirmTarget, setResetConfirmTarget] = useState(false);
  const [deepseekQuota, setDeepseekQuota] = useState<quotaApi.ProviderQuota | null>(null);
  const [deepseekBusy, setDeepseekBusy] = useState(false);
  const [zhipuQuota, setZhipuQuota] = useState<quotaApi.ProviderQuota | null>(null);
  const [zhipuBusy, setZhipuBusy] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Check ChatGPT auth status when a chatgpt provider exists
  const chatgptProvider = providers.find((p) => p.type === "chatgpt");
  useEffect(() => {
    if (chatgptProvider) {
      chatgptApi.getAuthStatus().then(setChatgptAuth).catch(() => {});
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [chatgptProvider?.name]);

  const handleChatgptLogin = async () => {
    setChatgptBusy(true);
    try {
      const code = await chatgptApi.startDeviceCode();
      setChatgptDeviceCode(code);
      // Start polling
      setChatgptPolling(true);
      const poll = async () => {
        try {
          const status = await chatgptApi.pollDeviceAuth(code.device_auth_id, code.user_code);
          if (status.authenticated) {
            setChatgptAuth(status);
            setChatgptPolling(false);
            setChatgptDeviceCode(null);
            if (pollRef.current) clearInterval(pollRef.current);
            toast.success("ChatGPT 登录成功");
          }
        } catch {
          // Ignore polling errors
        }
      };
      pollRef.current = setInterval(poll, (code.interval || 5) * 1000);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to start login");
    } finally {
      setChatgptBusy(false);
    }
  };

  const handleChatgptLogout = async () => {
    try {
      await chatgptApi.logout();
      setChatgptAuth({ authenticated: false });
      setChatgptAccount(null);
      toast.success("已退出 ChatGPT 登录");
    } catch {
      toast.error("退出失败");
    }
  };

  const handleChatgptAccountInfo = async () => {
    setChatgptAccountBusy(true);
    try {
      const info = await chatgptApi.getAccountInfo();
      setChatgptAccount(info);
    } catch {
      toast.error("获取账户信息失败");
    } finally {
      setChatgptAccountBusy(false);
    }
  };

  const handleConsumeReset = () => {
    const credits = chatgptAccount?.rate_limits?.banked_resets;
    const available = credits?.available_count ?? 0;
    if (available <= 0) {
      toast.error("没有可用的重置额度");
      return;
    }
    setResetConfirmTarget(true);
  };

  const handleConfirmReset = async () => {
    const credits = chatgptAccount?.rate_limits?.banked_resets;
    const firstCredit = credits?.credits?.[0];
    const creditId = firstCredit?.id;
    if (!creditId) {
      toast.error("无法获取重置额度 ID");
      return;
    }
    setResetConfirmTarget(false);
    setResetBusy(true);
    try {
      await chatgptApi.consumeResetCredit(creditId);
      toast.success("额度已重置！");
      // Refresh account info after reset
      const info = await chatgptApi.getAccountInfo();
      setChatgptAccount(info);
    } catch {
      toast.error("重置失败，请稍后重试");
    } finally {
      setResetBusy(false);
    }
  };

  const handleDeepSeekQuota = async (name: string) => {
    setDeepseekBusy(true);
    try {
      const info = await quotaApi.getProviderQuota(name);
      setDeepseekQuota(info);
    } catch {
      toast.error("获取 DeepSeek 余额失败");
    } finally {
      setDeepseekBusy(false);
    }
  };

  const handleZhipuQuota = async (name: string) => {
    setZhipuBusy(true);
    try {
      const info = await quotaApi.getProviderQuota(name);
      setZhipuQuota(info);
    } catch {
      toast.error("获取智谱额度失败");
    } finally {
      setZhipuBusy(false);
    }
  };

  const handleAddExtraModel = async (providerName: string) => {
    const modelId = (newModelInput[providerName] || "").trim();
    if (!modelId) return;
    const provider = providers.find((p) => p.name === providerName);
    if (!provider) return;
    const current = provider.extra_models || [];
    if (current.includes(modelId)) {
      toast.error("Model already exists");
      return;
    }
    setModelBusy(providerName);
    try {
      await providersApi.updateProvider(providerName, {
        extra_models: [...current, modelId],
      });
      toast.success(`Added model: ${modelId}`);
      emitProvidersChanged();
      onRefresh();
      setNewModelInput({ ...newModelInput, [providerName]: "" });
    } catch {
      toast.error("Failed to add model");
    } finally {
      setModelBusy(null);
    }
  };

  const handleRemoveExtraModel = async (providerName: string, modelId: string) => {
    const provider = providers.find((p) => p.name === providerName);
    if (!provider) return;
    const current = provider.extra_models || [];
    setModelBusy(`${providerName}:${modelId}`);
    try {
      await providersApi.updateProvider(providerName, {
        extra_models: current.filter((m) => m !== modelId),
      });
      toast.success(`Removed model: ${modelId}`);
      emitProvidersChanged();
      onRefresh();
    } catch {
      toast.error("Failed to remove model");
    } finally {
      setModelBusy(null);
    }
  };

  const handleToggleProxy = async (providerName: string) => {
    const provider = providers.find((p) => p.name === providerName);
    if (!provider) return;
    setProxyBusy(providerName);
    try {
      await providersApi.updateProvider(providerName, {
        proxy_enabled: !provider.proxy_enabled,
      });
      emitProvidersChanged();
      onRefresh();
    } catch {
      toast.error("Failed to toggle proxy");
    } finally {
      setProxyBusy(null);
    }
  };

  const handleSaveProxyUrl = async (providerName: string) => {
    const url = (proxyInput[providerName] ?? "").trim();
    const provider = providers.find((p) => p.name === providerName);
    if (!provider) return;
    // Skip if unchanged
    if (url === (provider.proxy_url ?? "")) return;
    setProxyBusy(`${providerName}:url`);
    try {
      await providersApi.updateProvider(providerName, { proxy_url: url });
      toast.success("Proxy URL saved");
      emitProvidersChanged();
      onRefresh();
    } catch {
      toast.error("Failed to save proxy URL");
    } finally {
      setProxyBusy(null);
    }
  };

  const handleAdd = async () => {
    setError(null);
    if (!formName || !formType) {
      setError("Name and type are required");
      return;
    }
    // OAuth-based providers don't need api_key
    const isOAuth = selectedCatalog?.auth_type === "oauth";
    if (!isOAuth && !formKey) {
      setError("API key is required");
      return;
    }
    setBusy(true);
    try {
      await providersApi.createProvider({
        name: formName,
        type: formType,
        api_key: formKey,
        variant_id: formVariantId || undefined,
      });
      toast.success(t("provider.providerAdded"));
      emitProvidersChanged();
      onRefresh();
      setMode("list");
      setFormName("");
      setFormKey("");
      setFormVariantId("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to add provider");
    } finally {
      setBusy(false);
    }
  };

  const handleSetDefault = async (name: string) => {
    try {
      await providersApi.updateProvider(name, { is_default: true });
      toast.success(t("provider.defaultUpdated"));
      emitProvidersChanged();
      onRefresh();
    } catch {
      toast.error(t("provider.setDefaultFailed"));
    }
  };

  const handleDelete = async (name: string) => {
    try {
      await providersApi.deleteProvider(name);
      toast.success(t("provider.providerDeleted"));
      emitProvidersChanged();
      onRefresh();
    } catch {
      toast.error(t("provider.deleteFailed"));
    } finally {
      setDeleteTarget(null);
    }
  };

  const selectedCatalog = catalog.find((c) => c.type === formType);
  const selectedVariant = selectedCatalog?.variants.find((v) => v.id === formVariantId);
  const displayBaseUrl = selectedVariant?.base_url || selectedCatalog?.base_url;

  return (
    <>
      <Modal
        open={true}
        onOpenChange={(o) => !o && onClose()}
        title={mode === "list" ? t("provider.title") : t("provider.addProvider")}
        description={
          mode === "list"
            ? t("provider.manageDesc")
            : t("provider.configureDesc")
        }
        size="md"
        footer={
          mode === "add" ? (
            <>
              <Button variant="ghost" onClick={() => setMode("list")}>
                {t("common.cancel")}
              </Button>
              <Button variant="brand" loading={busy} onClick={handleAdd}>
                {t("provider.addProvider")}
              </Button>
            </>
          ) : (
            <Button variant="brand" onClick={() => setMode("add")}>
              <Plus size={14} /> {t("provider.addProvider")}
            </Button>
          )
        }
      >
        {mode === "list" ? (
          <div className="space-y-2">
            {providers.length === 0 ? (
              <EmptyState
                title={t("provider.noProviders")}
                description={t("provider.addProviderDesc")}
                action={
                  <Button variant="brand" size="sm" onClick={() => setMode("add")}>
                    <Plus size={14} /> {t("provider.addProvider")}
                  </Button>
                }
              />
            ) : (
              providers.map((p) => (
                <div
                  key={p.name}
                  className={cn(
                    "rounded-xl border border-[var(--border)]",
                    "bg-[var(--bg-tertiary)] overflow-hidden",
                  )}
                >
                  <div className="p-3 flex items-center justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-[var(--text-primary)] flex items-center gap-1.5">
                        <span className="truncate">{p.display_name}</span>
                        {p.is_default && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--brand-bg)] text-[var(--brand)] border border-[var(--brand-border)] flex items-center gap-1 shrink-0">
                            <Star size={9} /> default
                          </span>
                        )}
                        {(p.extra_models?.length ?? 0) > 0 && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-secondary)] text-[var(--text-tertiary)] border border-[var(--border)] shrink-0">
                            +{p.extra_models!.length} 模型
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-[var(--text-tertiary)] font-mono truncate">
                        {p.type} · {p.api_key_preview}
                      </div>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setExpandedProvider(expandedProvider === p.name ? null : p.name)}
                        title="额外模型"
                      >
                        {expandedProvider === p.name ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      </Button>
                      {!p.is_default && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleSetDefault(p.name)}
                          title={t("provider.setAsDefault")}
                        >
                          <StarOff size={14} />
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setDeleteTarget(p.name)}
                        title={t("common.delete")}
                        className="text-[var(--danger)] hover:text-[var(--danger)] hover:bg-[var(--danger-bg)]"
                      >
                        <Trash2 size={14} />
                      </Button>
                    </div>
                  </div>
                  {expandedProvider === p.name && (
                    <div className="px-3 pb-3 pt-1 border-t border-[var(--border)] space-y-3">
                      {/* ChatGPT OAuth Section */}
                      {p.type === "chatgpt" && (
                        <div className="pt-1.5 space-y-2">
                          <div className="text-[11px] font-medium text-[var(--text-secondary)] flex items-center gap-1.5">
                            ChatGPT 订阅登录
                            {chatgptAuth?.authenticated ? (
                              <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-green-500/15 text-green-600 border border-green-500/20">
                                <Check size={9} /> 已连接
                              </span>
                            ) : (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--danger-bg)] text-[var(--danger)] border border-[var(--danger-border)]">
                                未登录
                              </span>
                            )}
                          </div>

                          {/* Device Code Login UI */}
                          {chatgptDeviceCode && chatgptPolling && (
                            <div className="p-3 rounded-lg bg-[var(--bg-secondary)] border border-[var(--border)] space-y-2">
                              <p className="text-xs text-[var(--text-primary)]">
                                1. 打开下方链接，登录 ChatGPT 账号
                              </p>
                              <a
                                href={chatgptDeviceCode.verification_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 text-xs text-[var(--brand)] hover:underline"
                              >
                                {chatgptDeviceCode.verification_url}
                                <ExternalLink size={10} />
                              </a>
                              <p className="text-xs text-[var(--text-primary)]">2. 输入以下授权码：</p>
                              <div className="flex items-center gap-2">
                                <code className="px-3 py-1.5 rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border)] text-sm font-mono tracking-wider text-[var(--brand)]">
                                  {chatgptDeviceCode.user_code}
                                </code>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => {
                                    navigator.clipboard.writeText(chatgptDeviceCode.user_code);
                                    toast.success("已复制到剪贴板");
                                  }}
                                >
                                  复制
                                </Button>
                              </div>
                              <div className="flex items-center gap-1.5 text-[11px] text-[var(--text-tertiary)]">
                                <Loader2 size={10} className="animate-spin" />
                                等待授权完成...
                              </div>
                            </div>
                          )}

                          {/* Auth Buttons */}
                          <div className="flex items-center gap-2">
                            {chatgptAuth?.authenticated ? (
                              <>
                                <Button variant="secondary" size="sm" onClick={handleChatgptAccountInfo} loading={chatgptAccountBusy}>
                                  {chatgptAccountBusy ? "查询中..." : "查看额度"}
                                </Button>
                                <Button variant="ghost" size="sm" onClick={handleChatgptLogout} className="text-[var(--danger)]">
                                  退出登录
                                </Button>
                              </>
                            ) : (
                              <Button variant="brand" size="sm" onClick={handleChatgptLogin} loading={chatgptBusy}>
                                登录 ChatGPT
                              </Button>
                            )}
                          </div>

                          {/* Account Info Display */}
                          {chatgptAccount && (
                            <div className="p-3 rounded-lg bg-[var(--bg-secondary)] border border-[var(--border)] text-[11px] space-y-2">
                              {/* Basic info */}
                              <div className="flex justify-between">
                                <span className="text-[var(--text-tertiary)]">邮箱</span>
                                <span className="text-[var(--text-primary)]">{chatgptAccount.email || "—"}</span>
                              </div>
                              <div className="flex justify-between">
                                <span className="text-[var(--text-tertiary)]">订阅</span>
                                <span className="px-1.5 py-0.5 rounded bg-[var(--brand-bg)] text-[var(--brand)] border border-[var(--brand-border)] font-medium uppercase text-[10px]">
                                  {chatgptAccount.plan || "?"}
                                </span>
                              </div>

                              {/* Real-time usage */}
                              {chatgptAccount.rate_limits && !chatgptAccount.rate_limits.error && (
                                <div className="pt-2 border-t border-[var(--border)] space-y-2.5">
                                  <div className="text-[var(--text-secondary)] font-medium flex items-center gap-1.5">
                                    实时额度
                                    {chatgptAccount.rate_limits.active_limit && (
                                      <span className="text-[10px] px-1 py-0.5 rounded bg-[var(--bg-tertiary)] text-[var(--text-tertiary)]">
                                        {chatgptAccount.rate_limits.active_limit}
                                      </span>
                                    )}
                                  </div>

                                  {/* Primary window — label and format are derived from raw seconds */}
                                  {chatgptAccount.rate_limits.primary && (
                                    <UsageBar
                                      label={formatWindow(chatgptAccount.rate_limits.primary.window_seconds) || "使用窗口"}
                                      usedPercent={chatgptAccount.rate_limits.primary.used_percent}
                                      windowText={
                                        chatgptAccount.rate_limits.primary.window_seconds
                                          ? formatWindow(chatgptAccount.rate_limits.primary.window_seconds).replace("窗口", "滚动窗口")
                                          : ""
                                      }
                                      resetText={formatReset(chatgptAccount.rate_limits.primary.reset_after_seconds)}
                                    />
                                  )}

                                  {/* Secondary window — only rendered when API returns one */}
                                  {chatgptAccount.rate_limits.secondary && (
                                    <UsageBar
                                      label={formatWindow(chatgptAccount.rate_limits.secondary.window_seconds) || "次级窗口"}
                                      usedPercent={chatgptAccount.rate_limits.secondary.used_percent}
                                      windowText={
                                        chatgptAccount.rate_limits.secondary.window_seconds
                                          ? formatWindow(chatgptAccount.rate_limits.secondary.window_seconds).replace("窗口", "滚动窗口")
                                          : ""
                                      }
                                      resetText={formatReset(chatgptAccount.rate_limits.secondary.reset_after_seconds)}
                                    />
                                  )}

                                  {/* Credits */}
                                  {chatgptAccount.rate_limits.credits && (
                                    <div className="flex justify-between text-[10px] text-[var(--text-tertiary)]">
                                      <span>Credits</span>
                                      <span>
                                        {chatgptAccount.rate_limits.credits.unlimited ? "无限" :
                                         chatgptAccount.rate_limits.credits.has_credits ? `余额: ${chatgptAccount.rate_limits.credits.balance || "—"}` :
                                         "无额外 credits"}
                                      </span>
                                    </div>
                                  )}

                                  {/* Banked Rate-Limit Resets */}
                                  {chatgptAccount.rate_limits.banked_resets && (
                                    <div className="pt-2 border-t border-[var(--border)] space-y-1.5">
                                      <div className="flex items-center justify-between">
                                        <span className="text-[var(--text-secondary)] font-medium">手动重置额度</span>
                                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${chatgptAccount.rate_limits.banked_resets.available_count && chatgptAccount.rate_limits.banked_resets.available_count > 0 ? "bg-[var(--success-bg)] text-[var(--success)]" : "bg-[var(--bg-tertiary)] text-[var(--text-tertiary)]"}`}>
                                          {chatgptAccount.rate_limits.banked_resets.available_count ?? 0} 个可用
                                        </span>
                                      </div>
                                      {chatgptAccount.rate_limits.banked_resets.credits && chatgptAccount.rate_limits.banked_resets.credits.length > 0 && (
                                        <div className="space-y-1">
                                          {chatgptAccount.rate_limits.banked_resets.credits.map((c, idx) => (
                                            <div key={c.id || idx} className="flex justify-between text-[10px] text-[var(--text-tertiary)]">
                                              <span>{c.reset_type === "codex_rate_limits" ? "Codex 限流重置" : c.reset_type || "限流重置"}</span>
                                              {c.expires_at && <span>过期: {new Date(c.expires_at).toLocaleDateString("zh-CN")}</span>}
                                            </div>
                                          ))}
                                        </div>
                                      )}
                                      {(chatgptAccount.rate_limits.banked_resets.available_count ?? 0) > 0 && (
                                        <Button
                                          variant="brand"
                                          size="sm"
                                          onClick={handleConsumeReset}
                                          loading={resetBusy}
                                          className="w-full mt-1"
                                        >
                                          {resetBusy ? "重置中..." : "⚡ 立即使用重置"}
                                        </Button>
                                      )}
                                    </div>
                                  )}
                                </div>
                              )}

                              {chatgptAccount.rate_limits?.error && (
                                <div className="pt-2 border-t border-[var(--border)] text-[var(--danger)]">
                                  {chatgptAccount.rate_limits.error}
                                </div>
                              )}

                              {!chatgptAccount.email && !chatgptAccount.plan && (
                                <div className="text-[var(--text-tertiary)]">无法获取账户信息，请重新登录</div>
                              )}
                            </div>
                          )}
                        </div>
                      )}

                      {/* DeepSeek Quota Section */}
                      {p.type === "deepseek" && (
                        <div className="pt-1.5 space-y-2">
                          <div className="flex items-center gap-2">
                            <Button variant="secondary" size="sm" onClick={() => handleDeepSeekQuota(p.name)} loading={deepseekBusy}>
                              {deepseekBusy ? "查询中..." : "查看余额"}
                            </Button>
                          </div>
                          {deepseekQuota && (
                            <div className="p-3 rounded-lg bg-[var(--bg-secondary)] border border-[var(--border)] text-[11px] space-y-2">
                              <div className="flex justify-between">
                                <span className="text-[var(--text-tertiary)]">可用</span>
                                <span className={(deepseekQuota.summary as quotaApi.DeepSeekQuota).is_available ? "text-green-500" : "text-[var(--danger)]"}>
                                  {(deepseekQuota.summary as quotaApi.DeepSeekQuota).is_available ? "是" : "否"}
                                </span>
                              </div>
                              {(deepseekQuota.summary as quotaApi.DeepSeekQuota).balances.map((b, i) => (
                                <div key={i} className="pt-1.5 border-t border-[var(--border)] space-y-1.5">
                                  <div className="text-[var(--text-secondary)] font-medium">
                                    {b.currency === "CNY" ? "💴 人民币" : "💵 美元"}
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-[var(--text-tertiary)]">总余额</span>
                                    <span className="text-[var(--text-primary)] font-medium">{b.total}</span>
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-[var(--text-tertiary)]">充值余额</span>
                                    <span className="text-[var(--text-primary)]">{b.topped_up}</span>
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-[var(--text-tertiary)]">赠送余额</span>
                                    <span className="text-[var(--text-primary)]">{b.granted}</span>
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      {/* Zhipu Quota Section */}
                      {p.type === "zhipu" && (
                        <div className="pt-1.5 space-y-2">
                          <div className="flex items-center gap-2">
                            <Button variant="secondary" size="sm" onClick={() => handleZhipuQuota(p.name)} loading={zhipuBusy}>
                              {zhipuBusy ? "查询中..." : "查看额度"}
                            </Button>
                          </div>
                          {zhipuQuota && (
                            <div className="p-3 rounded-lg bg-[var(--bg-secondary)] border border-[var(--border)] text-[11px] space-y-2">
                              <div className="flex justify-between">
                                <span className="text-[var(--text-tertiary)]">套餐等级</span>
                                <span className="px-1.5 py-0.5 rounded bg-[var(--brand-bg)] text-[var(--brand)] border border-[var(--brand-border)] font-medium uppercase text-[10px]">
                                  {(zhipuQuota.summary as quotaApi.ZhipuQuota).level || "?"}
                                </span>
                              </div>
                              {(zhipuQuota.summary as quotaApi.ZhipuQuota).token_limits.map((tl, i) => (
                                <div key={i} className="pt-2 border-t border-[var(--border)]">
                                  <UsageBar
                                    label={tl.label === "WEEK" ? "📅 周窗口" : `⏱ ${tl.number} 小时窗口`}
                                    usedPercent={tl.percentage}
                                    resetText={formatResetCountdown(tl.nextResetTime)}
                                  />
                                </div>
                              ))}
                              {(zhipuQuota.summary as quotaApi.ZhipuQuota).time_limit && (
                                <div className="pt-2 border-t border-[var(--border)] space-y-1.5">
                                  <div className="text-[var(--text-secondary)] font-medium">📊 MCP 月度配额</div>
                                  <UsageBar
                                    label="已用"
                                    usedPercent={(zhipuQuota.summary as quotaApi.ZhipuQuota).time_limit!.percentage}
                                  />
                                  <div className="flex justify-between text-[10px] text-[var(--text-tertiary)]">
                                    <span>
                                      剩余: {(zhipuQuota.summary as quotaApi.ZhipuQuota).time_limit!.remaining} /{" "}
                                      {(zhipuQuota.summary as quotaApi.ZhipuQuota).time_limit!.usage}
                                    </span>
                                    {(zhipuQuota.summary as quotaApi.ZhipuQuota).time_limit!.nextResetTime && (
                                      <span>
                                        {formatResetCountdown((zhipuQuota.summary as quotaApi.ZhipuQuota).time_limit!.nextResetTime!)}
                                      </span>
                                    )}
                                  </div>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      )}

                      {/* Proxy Section */}
                      <div className="pt-1.5">
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="text-[11px] font-medium text-[var(--text-secondary)]">
                            网络代理
                          </span>
                          <button
                            onClick={() => handleToggleProxy(p.name)}
                            disabled={proxyBusy === p.name}
                            className={cn(
                              "relative inline-flex h-4 w-7 items-center rounded-full transition-colors",
                              p.proxy_enabled ? "bg-[var(--brand)]" : "bg-[var(--bg-secondary)] border border-[var(--border)]",
                            )}
                          >
                            <span
                              className={cn(
                                "inline-block h-3 w-3 transform rounded-full bg-white transition-transform",
                                p.proxy_enabled ? "translate-x-3.5" : "translate-x-0.5",
                              )}
                            />
                          </button>
                        </div>
                        {p.proxy_enabled && (
                          <div className="flex items-center gap-1.5">
                            <input
                              type="text"
                              value={proxyInput[p.name] ?? p.proxy_url ?? ""}
                              onChange={(e) => setProxyInput({ ...proxyInput, [p.name]: e.target.value })}
                              onKeyDown={(e) => { if (e.key === "Enter") handleSaveProxyUrl(p.name); }}
                              placeholder="代理地址（留空则使用全局代理）"
                              className="flex-1 h-8 px-2.5 text-xs rounded-lg bg-[var(--bg-secondary)] border border-[var(--border)] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--brand)] focus:ring-1 focus:ring-[var(--brand)]/30"
                            />
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() => handleSaveProxyUrl(p.name)}
                              loading={proxyBusy === `${p.name}:url`}
                            >
                              <Check size={12} />
                            </Button>
                          </div>
                        )}
                        <p className="text-[10px] text-[var(--text-tertiary)] mt-1">
                          启用后此 Provider 的请求将通过代理访问
                        </p>
                      </div>

                      {/* Extra Models Section */}
                      <div className="border-t border-[var(--border)] pt-2">
                        <div className="text-[11px] font-medium text-[var(--text-secondary)] mb-1.5">
                          额外模型（API 未返回但可调用的模型）
                        </div>
                      <div className="flex flex-wrap gap-1.5">
                        {(p.extra_models || []).map((m) => (
                          <span
                            key={m}
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-[var(--bg-secondary)] border border-[var(--border)] text-xs text-[var(--text-primary)] font-mono"
                          >
                            {m}
                            <button
                              onClick={() => handleRemoveExtraModel(p.name, m)}
                              disabled={modelBusy === `${p.name}:${m}`}
                              className="text-[var(--text-tertiary)] hover:text-[var(--danger)] transition-colors"
                            >
                              <X size={11} />
                            </button>
                          </span>
                        ))}
                        {(p.extra_models || []).length === 0 && (
                          <span className="text-[11px] text-[var(--text-tertiary)]">暂无额外模型</span>
                        )}
                      </div>
                      <div className="flex items-center gap-1.5">
                        <input
                          type="text"
                          value={newModelInput[p.name] || ""}
                          onChange={(e) => setNewModelInput({ ...newModelInput, [p.name]: e.target.value })}
                          onKeyDown={(e) => { if (e.key === "Enter") handleAddExtraModel(p.name); }}
                          placeholder="输入模型 ID，如 glm-5.2"
                          className="flex-1 h-8 px-2.5 text-xs rounded-lg bg-[var(--bg-secondary)] border border-[var(--border)] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--brand)] focus:ring-1 focus:ring-[var(--brand)]/30"
                        />
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => handleAddExtraModel(p.name)}
                          loading={modelBusy === p.name}
                        >
                          <Plus size={12} />
                        </Button>
                      </div>
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        ) : (
          <div className="space-y-4">
            {error && (
              <div className="px-3 py-2 rounded-lg bg-[var(--danger-bg)] border border-[var(--danger-border)] text-xs text-[var(--danger)]">
                {error}
              </div>
            )}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-[var(--text-secondary)]">
                Type
              </label>
              <select
                value={formType}
                onChange={(e) => {
                  setFormType(e.target.value);
                  setFormVariantId("");
                }}
                className="w-full h-9 px-3 text-sm rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--brand)] focus:ring-2 focus:ring-[var(--brand)]/30"
              >
                {catalog.map((c) => (
                  <option key={c.type} value={c.type}>
                    {c.display_name}
                  </option>
                ))}
              </select>
              {selectedCatalog && (
                <p className="text-[11px] text-[var(--text-tertiary)] font-mono">
                  Base URL: {selectedCatalog.auth_type === "oauth" ? "OAuth (无需 Base URL)" : displayBaseUrl}
                </p>
              )}
            </div>
            {selectedCatalog && selectedCatalog.variants.length > 0 && (
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-[var(--text-secondary)]">
                  Variant
                </label>
                <select
                  value={formVariantId}
                  onChange={(e) => setFormVariantId(e.target.value)}
                  className="w-full h-9 px-3 text-sm rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--brand)] focus:ring-2 focus:ring-[var(--brand)]/30"
                >
                  <option value="">{t("provider.defaultLabel")}</option>
                  {selectedCatalog.variants.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.display_name}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <Input
              label={t("provider.name")}
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              placeholder={t("provider.namePlaceholder2")}
            />
            {selectedCatalog?.auth_type === "oauth" ? (
              <div className="px-3 py-3 rounded-lg bg-[var(--brand-bg)] border border-[var(--brand-border)] text-xs text-[var(--text-secondary)]">
                <div className="font-medium text-[var(--text-primary)] mb-1">🔒 OAuth 认证</div>
                <p>此 Provider 使用 ChatGPT 订阅登录，无需 API Key。</p>
                <p className="mt-1">添加后请在 Provider 列表中点击「登录 ChatGPT」完成授权。</p>
                {selectedCatalog.models && selectedCatalog.models.length > 0 && (
                  <p className="mt-1 text-[var(--text-tertiary)]">
                    可用模型: {selectedCatalog.models.slice(0, 4).join(", ")}
                    {selectedCatalog.models.length > 4 ? " ..." : ""}
                  </p>
                )}
              </div>
            ) : (
              <PasswordInput
                label={t("provider.apiKey")}
                value={formKey}
                onChange={(e) => setFormKey(e.target.value)}
                placeholder={t("provider.apiKeyPlaceholder2")}
              />
            )}
          </div>
        )}
      </Modal>

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        title={`Delete provider "${deleteTarget}"?`}
        description={t("provider.deleteProviderDesc")}
        confirmText={t("common.delete")}
        tone="danger"
        onConfirm={() => { if (deleteTarget) handleDelete(deleteTarget); }}
      />

      {/* Reset credit confirmation */}
      <ConfirmDialog
        open={resetConfirmTarget}
        onOpenChange={setResetConfirmTarget}
        title="确认重置额度"
        description="此操作将立即消耗一张重置卡，清除当前 5 小时窗口和 7 天窗口的使用量。确定要继续吗？"
        confirmText="确认重置"
        tone="warning"
        onConfirm={handleConfirmReset}
      />
    </>
  );
}

/** 将时间戳（ms 或 s）转换为倒计时文本，如 "3天2h后重置" 或 "15min后重置" */
function formatResetCountdown(nextResetTime?: number): string {
  if (!nextResetTime) return "";
  // 兼容秒级和毫秒级时间戳
  const ts = nextResetTime > 1e12 ? nextResetTime : nextResetTime * 1000;
  const diff = ts - Date.now();
  if (diff <= 0) return "已可重置";
  const min = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);
  if (days > 0) return `${days}天${hours % 24}h后重置`;
  if (hours > 0) return `${hours}h${min % 60}min后重置`;
  return `${min}min后重置`;
}

function UsageBar({
  label,
  usedPercent,
  windowText,
  resetText,
}: {
  label: string;
  usedPercent: number | null | undefined;
  windowText?: string;
  resetText?: string;
}) {
  const pct = usedPercent ?? 0;
  const barColor = pct >= 80 ? "bg-[var(--danger)]" : pct >= 50 ? "bg-amber-500" : "bg-[var(--brand)]";
  return (
    <div className="space-y-1">
      <div className="flex justify-between items-center">
        <span className="text-[var(--text-tertiary)]">{label}</span>
        <span className="text-[var(--text-primary)] font-medium">{pct.toFixed(1)}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-[var(--bg-tertiary)] overflow-hidden">
        <div className={cn("h-full rounded-full transition-all duration-500", barColor)} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      {(windowText || resetText) && (
        <div className="flex justify-between text-[10px] text-[var(--text-tertiary)]">
          <span>{windowText}</span>
          <span>{resetText}</span>
        </div>
      )}
    </div>
  );
}

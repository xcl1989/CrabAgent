import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Accessibility, Camera, Plus, RefreshCw, X, ShieldAlert, ShieldCheck } from "lucide-react";
import { Button } from "./ui";
import { toast } from "./ui/Toast";

type MacosPermissions = {
  accessibility: boolean;
  screenRecording: boolean;
  secureInput: boolean;
  osVersion: string;
};

type MacosConfig = { inputEnabled: boolean; allowlist: string[] };

type MacosStatus = {
  config: MacosConfig;
  permissions: MacosPermissions | null;
  helperAvailable: boolean;
  error: string | null;
};

// macOS Computer Use settings (M1): TCC permission status with deep links,
// input opt-in toggle and the app allowlist. All writes go through the
// Electron main process; the renderer never touches the helper.
export default function MacosComputerPanel() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<MacosStatus | null>(null);
  const [inputEnabled, setInputEnabled] = useState(false);
  const [allowlist, setAllowlist] = useState<string[]>([]);
  const [newEntry, setNewEntry] = useState("");
  const [saving, setSaving] = useState(false);
  const [rechecking, setRechecking] = useState(false);

  const applyStatus = useCallback((next: MacosStatus) => {
    setStatus(next);
    setInputEnabled(next.config.inputEnabled);
    setAllowlist(next.config.allowlist);
  }, []);

  const refresh = useCallback(async () => {
    setRechecking(true);
    try {
      const next = await window.electronAPI?.macosComputerGetStatus?.();
      if (next) applyStatus(next);
    } finally {
      setRechecking(false);
    }
  }, [applyStatus]);

  useEffect(() => { void refresh(); }, [refresh]);

  const save = useCallback(async (nextConfig: MacosConfig) => {
    setSaving(true);
    try {
      const next = await window.electronAPI?.macosComputerSetConfig?.(nextConfig);
      if (next) applyStatus(next);
    } finally {
      setSaving(false);
    }
  }, [applyStatus]);

  if (!window.electronAPI?.macosComputerGetStatus) {
    return <p className="text-sm text-[var(--text-secondary)]">仅在桌面应用中可用。</p>;
  }

  const perm = status?.permissions;
  const permRow = (label: string, granted: boolean | undefined, kind: "accessibility" | "screenRecording") => (
    <div className="flex items-center justify-between gap-2 py-1.5">
      <span className="flex items-center gap-1.5 text-sm">
        {kind === "accessibility" ? <Accessibility size={14} /> : <Camera size={14} />}
        {label}
      </span>
      <span className="flex items-center gap-2">
        {granted ? (
          <span className="flex items-center gap-1 text-xs text-[var(--success)]"><ShieldCheck size={13} />已授权</span>
        ) : (
          <span className="flex items-center gap-1 text-xs text-[var(--warning, #d97706)]"><ShieldAlert size={13} />未授权</span>
        )}
        {!granted && (
          <Button
            variant="ghost"
            className="h-6 px-2 text-xs"
            onClick={async () => {
              try {
                const opened = await window.electronAPI?.macosComputerOpenSettings?.(kind);
                if (!opened) toast.error("无法打开系统设置，请手动打开：系统设置 → 隐私与安全性");
              } catch (e) {
                toast.error(`打开系统设置失败：${e instanceof Error ? e.message : String(e)}`);
              }
            }}
          >
            去授权
          </Button>
        )}
      </span>
    </div>
  );

  return (
    <div className="space-y-4 text-[var(--text-primary)]">
      <div>
        <h3 className="text-sm font-semibold">macOS Computer Use</h3>
        <p className="mt-1 text-xs text-[var(--text-secondary)]">
          允许 AI 观察和操作本机应用窗口。默认关闭；开启后 AI 只能操作下方允许列表内的前台应用，随时可暂停。
        </p>
      </div>

      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-3">
        <div className="mb-1 flex items-center justify-between">
          <span className="text-xs font-medium text-[var(--text-secondary)]">系统权限</span>
          <Button variant="ghost" className="h-6 px-2 text-xs" disabled={rechecking} onClick={() => void refresh()}>
            <RefreshCw size={12} className={rechecking ? "animate-spin" : ""} />重新检测
          </Button>
        </div>
        {!status?.helperAvailable ? (
          <p className="text-xs text-[var(--warning, #d97706)]">helper 未编译（运行 npm run build-helper）</p>
        ) : perm ? (
          <>
            {permRow("辅助功能（Accessibility）", perm.accessibility, "accessibility")}
            {permRow("屏幕录制（Screen Recording）", perm.screenRecording, "screenRecording")}
            {perm.secureInput && (
              <p className="mt-1 text-xs text-[var(--warning, #d97706)]">Secure Input 激活中，输入动作已暂停。</p>
            )}
          </>
        ) : (
          <p className="text-xs text-[var(--warning, #d97706)]">无法获取权限状态：{status?.error}</p>
        )}
      </div>

      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">启用输入操作</span>
          <button
            type="button"
            role="switch"
            aria-checked={inputEnabled}
            disabled={saving}
            onClick={() => { const next = !inputEnabled; setInputEnabled(next); void save({ inputEnabled: next, allowlist }); }}
            className={`relative h-5 w-9 rounded-full transition-colors ${inputEnabled ? "bg-[var(--brand)]" : "bg-[var(--bg-tertiary)]"}`}
          >
            <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all ${inputEnabled ? "left-[18px]" : "left-0.5"}`} />
          </button>
        </div>
        <p className="mt-1 text-xs text-[var(--text-secondary)]">
          关闭时 AI 只能读取权限与窗口列表，不能模拟任何键鼠输入。
        </p>
      </div>

      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-3">
        <span className="text-sm font-medium">应用允许列表</span>
        <p className="mt-1 text-xs text-[var(--text-secondary)]">按 bundle ID 匹配（如 com.apple.TextEdit）。只有列表内应用处于前台时才允许输入。</p>
        <div className="mt-2 flex items-center gap-1.5">
          <input
            value={newEntry}
            onChange={(event) => setNewEntry(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && newEntry.trim()) {
                const next = [...new Set([...allowlist, newEntry.trim()])];
                setAllowlist(next); setNewEntry(""); void save({ inputEnabled, allowlist: next });
              }
            }}
            placeholder="com.apple.TextEdit"
            className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-2.5 py-1.5 text-sm outline-none focus-within:border-[var(--brand-border)]"
          />
          <Button
            variant="ghost"
            className="h-8 px-2"
            disabled={!newEntry.trim() || saving}
            onClick={() => { const next = [...new Set([...allowlist, newEntry.trim()])]; setAllowlist(next); setNewEntry(""); void save({ inputEnabled, allowlist: next }); }}
          >
            <Plus size={14} />
          </Button>
        </div>
        {allowlist.length > 0 && (
          <ul className="mt-2 space-y-1">
            {allowlist.map((bundleId) => (
              <li key={bundleId} className="flex items-center justify-between rounded-md bg-[var(--bg-primary)] px-2 py-1">
                <span className="truncate font-mono text-xs">{bundleId}</span>
                <button
                  type="button"
                  aria-label={`移除 ${bundleId}`}
                  disabled={saving}
                  className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                  onClick={() => { const next = allowlist.filter((x) => x !== bundleId); setAllowlist(next); void save({ inputEnabled, allowlist: next }); }}
                >
                  <X size={13} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

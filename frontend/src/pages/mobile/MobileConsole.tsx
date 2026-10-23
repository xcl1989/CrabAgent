/**
 * MobileConsole — /m 移动控制台入口（PWA standalone 主页面）。
 *
 * 路由约定（hash）：
 *   #/m                  → 任务流
 *   #/m/chat             → 会话时间线
 *   #/m/approve/<key>    → 深链落地：任务流并高亮指定请求（只带 request_key，不带 token）
 *
 * 复用桌面端的 api client 与 LoginPage（登录一次，localStorage 长效）。
 * 桌面 UI 完全不受影响：App.tsx 仅在 hash 以 #/m 开头时渲染本组件。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import LoginPage from "../LoginPage";
import { MobileTaskFlow } from "./MobileTaskFlow";
import { MobileTimeline } from "./MobileTimeline";

type Tab = "tasks" | "chat";

function parseHash(): { tab: Tab; focusKey?: string } {
  const h = window.location.hash.replace(/^#\/m\/?/, "");
  if (h.startsWith("approve/")) {
    return { tab: "tasks", focusKey: h.slice("approve/".length) };
  }
  if (h.startsWith("chat")) return { tab: "chat" };
  return { tab: "tasks" };
}

export function MobileConsole() {
  const { t } = useTranslation();
  const [authed, setAuthed] = useState(!!api.getToken());
  const initial = useMemo(parseHash, []);
  const [tab, setTab] = useState<Tab>(initial.tab);
  const [focusKey, setFocusKey] = useState<string | undefined>(initial.focusKey);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [healthOk, setHealthOk] = useState<boolean | null>(null);

  // 连接健康检查（Mac 离线 / Tailscale 未连时给出明确降级提示）
  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const res = await fetch("/health", { signal: AbortSignal.timeout(5000) });
        if (!cancelled) setHealthOk(res.ok);
      } catch {
        if (!cancelled) setHealthOk(false);
      }
    };
    void check();
    const timer = setInterval(check, 15000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const openSession = useCallback((sid: string) => {
    setSessionId(sid);
    setTab("chat");
    window.location.hash = "#/m/chat";
  }, []);

  const switchTab = useCallback((next: Tab) => {
    setTab(next);
    setFocusKey(undefined);
    window.location.hash = next === "chat" ? "#/m/chat" : "#/m";
  }, []);

  if (!authed) {
    return <LoginPage onLogin={() => setAuthed(true)} />;
  }

  return (
    <div className="flex flex-col h-dvh bg-zinc-950 text-zinc-100">
      {/* 顶栏 */}
      <header
        className="flex-shrink-0 border-b border-zinc-800 bg-zinc-950/95 px-4 pb-2.5"
        style={{ paddingTop: "calc(0.75rem + env(safe-area-inset-top))" }}
      >
        <div className="flex items-center justify-between">
          <h1 className="text-[19px] font-bold tracking-tight">🦀 CrabAgent</h1>
          <button
            onClick={() => api.clearToken()}
            className="text-[11px] text-zinc-500 border border-zinc-700 rounded-full px-2.5 py-1"
          >
            {t("mobile.logout")}
          </button>
        </div>
        <div className="flex items-center gap-1.5 mt-1 text-[12px] text-zinc-500">
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full ${
              healthOk === false ? "bg-red-500" : healthOk ? "bg-green-500" : "bg-zinc-500"
            }`}
          />
          {healthOk === false
            ? t("mobile.offline")
            : healthOk
              ? t("mobile.connected")
              : t("mobile.connecting")}
        </div>
      </header>

      {/* 主区 */}
      <main className="flex-1 relative overflow-hidden">
        <div className={`absolute inset-0 overflow-y-auto ${tab !== "tasks" && "hidden"}`}>
          <MobileTaskFlow focusKey={focusKey} onOpenSession={openSession} />
        </div>
        <div className={`absolute inset-0 ${tab !== "chat" && "hidden"}`}>
          <MobileTimeline sessionId={sessionId} onSessionChange={setSessionId} />
        </div>
      </main>

      {/* 底部 Tab（P1：任务 / 会话；文档、设置随 P2/P3 扩展） */}
      <nav
        className="flex-shrink-0 border-t border-zinc-800 bg-zinc-950/95 backdrop-blur flex"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        {(
          [
            { id: "tasks", icon: "◈", label: t("mobile.tabTasks") },
            { id: "chat", icon: "▤", label: t("mobile.tabSessions") },
          ] as const
        ).map(({ id, icon, label }) => (
          <button
            key={id}
            onClick={() => switchTab(id)}
            className={`flex-1 py-2.5 text-[10px] flex flex-col items-center gap-0.5 ${
              tab === id ? "text-blue-400" : "text-zinc-500"
            }`}
          >
            <span className="text-[18px]">{icon}</span>
            {label}
          </button>
        ))}
      </nav>
    </div>
  );
}

import { useState, useEffect, useCallback } from "react";
import { api } from "./api/client";
import LoginPage from "./pages/LoginPage";
import ChatPage from "./pages/ChatPage";
import AgentsPage from "./pages/AgentsPage";
import MemoryPage from "./pages/MemoryPage";
import SettingsPage from "./pages/SettingsPage";
import UsagePage from "./pages/UsagePage";
import CalendarPage from "./pages/CalendarPage";
import { NavBar } from "./components/NavBar";
import { cn } from "./lib/cn";
import { connectGlobalSSE } from "./api/monitor";
import { toast } from "./components/ui/Toast";
import { FtsStatusBar } from "./components/FtsStatusBar";

export type PageId = "chat" | "agents" | "memory" | "usage" | "calendar" | "settings";

interface FtsRebuild {
  in_progress: boolean;
  total: number;
  done: number;
}

function AuthenticatedApp({ onLogout }: { onLogout: () => void }) {
  const [page, setPage] = useState<PageId>("chat");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [ftsStatus, setFtsStatus] = useState<FtsRebuild | null>(null);

  // Lightweight health poll — only for FTS progress, never blocks the UI
  const checkHealth = useCallback(async () => {
    try {
      const res = await fetch("/health");
      if (res.ok) {
        const data = await res.json();
        const fts = data.fts_rebuild as FtsRebuild | undefined;
        setFtsStatus(fts ?? null);
      }
    } catch {
      // ignore — backend might still be starting
    }
  }, []);

  // Initial check + periodic poll while FTS is running
  useEffect(() => {
    checkHealth();
    const timer = setInterval(checkHealth, 3000);
    return () => clearInterval(timer);
  }, [checkHealth]);

  // Notify when FTS completes
  const ftsInProgress = ftsStatus?.in_progress;
  useEffect(() => {
    if (ftsStatus && !ftsStatus.in_progress && ftsStatus.total > 0) {
      toast.success("搜索引擎索引完成");
    }
  }, [ftsStatus?.in_progress]);

  // Connect to global SSE for system notifications
  useEffect(() => {
    const es = connectGlobalSSE((event) => {
      if (event.type === "notification") {
        const d = event.data as Record<string, string>;
        const text = d.text || "";
        toast.info(text);
      }
    });
    return () => es.close();
  }, []);

  return (
    <div className="flex flex-col h-dvh overflow-hidden">
      <NavBar currentPage={page} onNavigate={setPage} onLogout={onLogout} sessionId={activeSessionId} />
      <div className="flex-1 relative overflow-hidden">
        <div className={cn("absolute inset-0", page !== "chat" && "hidden")}>
          <ChatPage onActiveSessionChange={setActiveSessionId} />
        </div>
        <div className={cn("absolute inset-0", page !== "agents" && "hidden")}>
          <AgentsPage />
        </div>
        <div className={cn("absolute inset-0", page !== "memory" && "hidden")}>
          <MemoryPage />
        </div>
        <div className={cn("absolute inset-0", page !== "usage" && "hidden")}>
          <UsagePage />
        </div>
        <div className={cn("absolute inset-0", page !== "calendar" && "hidden")}>
          <CalendarPage />
        </div>
        <div className={cn("absolute inset-0", page !== "settings" && "hidden")}>
          <SettingsPage />
        </div>
      </div>

      {/* Non-blocking FTS indexing progress — bottom-right floating pill */}
      {ftsInProgress && ftsStatus && ftsStatus.total > 0 && (
        <FtsStatusBar done={ftsStatus.done} total={ftsStatus.total} />
      )}
    </div>
  );
}

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(!!api.getToken());

  const handleLogin = () => {
    setIsAuthenticated(true);
  };

  const handleLogout = () => {
    api.clearToken();
    setIsAuthenticated(false);
  };

  if (!isAuthenticated) {
    return <LoginPage onLogin={handleLogin} />;
  }

  return <AuthenticatedApp onLogout={handleLogout} />;
}

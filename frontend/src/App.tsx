import { useState } from "react";
import { api } from "./api/client";
import LoginPage from "./pages/LoginPage";
import ChatPage from "./pages/ChatPage";
import AgentsPage from "./pages/AgentsPage";
import MemoryPage from "./pages/MemoryPage";
import SettingsPage from "./pages/SettingsPage";
import UsagePage from "./pages/UsagePage";
import { NavBar } from "./components/NavBar";
import { cn } from "./lib/cn";

export type PageId = "chat" | "agents" | "memory" | "usage" | "settings";

function AuthenticatedApp({ onLogout }: { onLogout: () => void }) {
  const [page, setPage] = useState<PageId>("chat");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

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
        <div className={cn("absolute inset-0", page !== "settings" && "hidden")}>
          <SettingsPage />
        </div>
      </div>
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

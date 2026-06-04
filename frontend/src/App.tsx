import { useState } from "react";
import { api } from "./api/client";
import LoginPage from "./pages/LoginPage";
import ChatPage from "./pages/ChatPage";
import DashboardPage from "./pages/DashboardPage";
import AgentsPage from "./pages/AgentsPage";
import { NavBar } from "./components/NavBar";
import { cn } from "./lib/cn";

export type PageId = "chat" | "dashboard" | "agents";

function AuthenticatedApp({ onLogout }: { onLogout: () => void }) {
  const [page, setPage] = useState<PageId>("chat");

  return (
    <div className="flex flex-col h-dvh overflow-hidden">
      <NavBar currentPage={page} onNavigate={setPage} onLogout={onLogout} />
      <div className="flex-1 relative overflow-hidden">
        <div className={cn("absolute inset-0", page !== "chat" && "hidden")}>
          <ChatPage />
        </div>
        <div className={cn("absolute inset-0", page !== "dashboard" && "hidden")}>
          <DashboardPage />
        </div>
        <div className={cn("absolute inset-0", page !== "agents" && "hidden")}>
          <AgentsPage />
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

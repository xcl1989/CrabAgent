import { useState } from "react";
import { HashRouter, Routes, Route, Navigate } from "react-router-dom";
import { api } from "./api/client";
import LoginPage from "./pages/LoginPage";
import ChatPage from "./pages/ChatPage";
import DashboardPage from "./pages/DashboardPage";
import { NavBar } from "./components/NavBar";

function AuthenticatedApp({ onLogout }: { onLogout: () => void }) {
  return (
    <div className="flex flex-col h-screen">
      <NavBar />
      <Routes>
        <Route path="/chat" element={<ChatPage onLogout={onLogout} />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Routes>
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

  return (
    <HashRouter>
      <AuthenticatedApp onLogout={handleLogout} />
    </HashRouter>
  );
}

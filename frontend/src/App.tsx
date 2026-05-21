import { useState } from "react";
import { api } from "./api/client";
import LoginPage from "./pages/LoginPage";
import ChatPage from "./pages/ChatPage";

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
  return <ChatPage onLogout={handleLogout} />;
}

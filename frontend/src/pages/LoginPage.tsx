import { useState } from "react";
import { api } from "../api/client";
import * as authApi from "../api/auth";

interface Props {
  onLogin: () => void;
}

export default function LoginPage({ onLogin }: Props) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      if (mode === "login") {
        const res = await authApi.login(username, password);
        api.setToken(res.access_token);
        onLogin();
      } else {
        await authApi.register(username, password);
        const res = await authApi.login(username, password);
        api.setToken(res.access_token);
        onLogin();
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="w-full max-w-sm p-8 rounded-xl" style={{ background: "var(--bg-secondary)" }}>
        <h1 className="text-2xl font-bold text-center mb-6">CrabAgent</h1>

        <div className="flex mb-6 rounded-lg overflow-hidden" style={{ background: "var(--bg-tertiary)" }}>
          <button
            type="button"
            onClick={() => setMode("login")}
            className="flex-1 py-2 text-sm font-medium transition-colors"
            style={{
              background: mode === "login" ? "var(--accent)" : "transparent",
              color: mode === "login" ? "#fff" : "var(--text-secondary)",
            }}
          >
            Login
          </button>
          <button
            type="button"
            onClick={() => setMode("register")}
            className="flex-1 py-2 text-sm font-medium transition-colors"
            style={{
              background: mode === "register" ? "var(--accent)" : "transparent",
              color: mode === "register" ? "#fff" : "var(--text-secondary)",
            }}
          >
            Register
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="mb-4">
            <input
              type="text"
              placeholder="Username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-4 py-3 rounded-lg text-sm outline-none"
              style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              required
              minLength={2}
            />
          </div>
          <div className="mb-4">
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-3 rounded-lg text-sm outline-none"
              style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              required
              minLength={6}
            />
          </div>

          {error && <p className="text-sm mb-3" style={{ color: "var(--danger)" }}>{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 rounded-lg text-sm font-medium text-white transition-colors disabled:opacity-50"
            style={{ background: "var(--accent)" }}
          >
            {loading ? "..." : mode === "login" ? "Login" : "Register"}
          </button>
        </form>
      </div>
    </div>
  );
}

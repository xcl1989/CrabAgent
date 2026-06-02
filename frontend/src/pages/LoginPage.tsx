import { useState } from "react";
import { Loader2, AlertCircle } from "lucide-react";
import { api } from "../api/client";
import * as authApi from "../api/auth";
import { Input, PasswordInput, Button } from "../components/ui";
import { cn } from "../lib/cn";

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
    <div
      className="relative flex items-center justify-center min-h-screen overflow-hidden"
      style={{
        background:
          "radial-gradient(ellipse at top, var(--brand-bg) 0%, transparent 50%), radial-gradient(ellipse at bottom right, var(--accent-bg) 0%, transparent 50%), var(--bg-primary)",
      }}
    >
      {/* Decorative pattern */}
      <div
        className="absolute inset-0 opacity-[0.015] pointer-events-none"
        style={{
          backgroundImage:
            "radial-gradient(circle at 1px 1px, var(--text-primary) 1px, transparent 0)",
          backgroundSize: "24px 24px",
        }}
      />

      <div className="relative w-full max-w-sm mx-4 animate-slide-up">
        {/* Logo */}
        <div className="flex flex-col items-center mb-6">
          <div
            className="w-14 h-14 rounded-2xl flex items-center justify-center text-2xl mb-3 shadow-[var(--shadow-lg)]"
            style={{
              background:
                "linear-gradient(135deg, var(--brand) 0%, var(--brand-active) 100%)",
            }}
          >
            🦀
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">
            CrabAgent
          </h1>
          <p className="text-xs text-[var(--text-tertiary)] mt-1">
            Your AI coding companion
          </p>
        </div>

        {/* Card */}
        <div
          className="rounded-2xl p-6 backdrop-blur-md border"
          style={{
            background: "var(--bg-secondary)",
            borderColor: "var(--border)",
            boxShadow: "var(--shadow-lg), var(--shadow-inset)",
          }}
        >
          {/* Mode toggle */}
          <div className="flex p-1 mb-5 rounded-lg bg-[var(--bg-tertiary)]">
            {(["login", "register"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={cn(
                  "flex-1 py-1.5 rounded-md text-sm font-medium transition-all",
                  mode === m
                    ? "bg-[var(--bg-secondary)] text-[var(--text-primary)] shadow-[var(--shadow-sm)]"
                    : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
                )}
              >
                {m === "login" ? "Sign In" : "Sign Up"}
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              label="Username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Choose a username"
              required
              minLength={2}
              autoComplete="username"
            />
            <PasswordInput
              label="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 6 characters"
              required
              minLength={6}
              autoComplete={
                mode === "login" ? "current-password" : "new-password"
              }
            />

            {error && (
              <div
                role="alert"
                className="flex items-start gap-2 px-3 py-2 rounded-lg bg-[var(--danger-bg)] border border-[var(--danger-border)] text-xs text-[var(--danger)]"
              >
                <AlertCircle size={14} className="mt-px shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <Button
              type="submit"
              variant="brand"
              size="lg"
              fullWidth
              loading={loading}
            >
              {mode === "login" ? "Sign In" : "Create Account"}
            </Button>
          </form>

          <p className="text-[11px] text-[var(--text-tertiary)] text-center mt-4">
            {mode === "login" ? "Default: admin / xcl1989" : ""}
          </p>
        </div>

        <p className="text-[11px] text-center mt-6 text-[var(--text-tertiary)]">
          v0.7.2 · Local-first AI agent platform
        </p>
      </div>
    </div>
  );
}

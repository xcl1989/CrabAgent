import { useState } from "react";
import { Loader2, AlertCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import * as authApi from "../api/auth";
import { Input, PasswordInput, Button } from "../components/ui";
import { cn } from "../lib/cn";
import { SUPPORTED_LANGUAGES } from "../i18n";

interface Props {
  onLogin: () => void;
}

export default function LoginPage({ onLogin }: Props) {
  const { t, i18n } = useTranslation();
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
            {t("login.title")}
          </h1>
          <p className="text-xs text-[var(--text-tertiary)] mt-1">
            {t("login.subtitle")}
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
                {m === "login" ? t("login.signIn") : t("login.signUp")}
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              label={t("login.username")}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder={t("login.usernamePlaceholder")}
              required
              minLength={2}
              autoComplete="username"
            />
            <PasswordInput
              label={t("login.password")}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={t("login.passwordPlaceholder")}
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
              {mode === "login" ? t("login.signIn") : t("login.createAccount")}
            </Button>
          </form>

          <p className="text-[11px] text-[var(--text-tertiary)] text-center mt-4">
            {mode === "login" ? t("login.defaultHint") : ""}
          </p>
        </div>

        <div className="flex items-center justify-between mt-6">
          <p className="text-[11px] text-[var(--text-tertiary)]">
            {t("login.version")}
          </p>
          {/* Language switch on login page */}
          <div className="flex gap-1">
            {SUPPORTED_LANGUAGES.map((lang) => (
              <button
                key={lang.code}
                onClick={() => {
                  i18n.changeLanguage(lang.code);
                  localStorage.setItem("crabagent-language", lang.code);
                }}
                className={cn(
                  "text-[11px] px-2 py-0.5 rounded transition-colors",
                  i18n.language === lang.code
                    ? "text-[var(--brand)] bg-[var(--brand-bg)]"
                    : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]",
                )}
              >
                {lang.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

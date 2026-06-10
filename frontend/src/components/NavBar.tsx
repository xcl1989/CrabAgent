import { MessageSquare, Users, Brain, Settings, Sun, Moon, LogOut, Globe, Coins } from "lucide-react";
import { useTheme } from "../lib/theme";
import { cn } from "../lib/cn";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Button } from "./ui";
import type { PageId } from "../App";
import { SUPPORTED_LANGUAGES, type LanguageCode } from "../i18n";

interface NavItem {
  id: PageId;
  labelKey: string;
  icon: React.ReactNode;
}

const items: NavItem[] = [
  { id: "chat", labelKey: "nav.chat", icon: <MessageSquare size={15} /> },
  { id: "agents", labelKey: "nav.agents", icon: <Users size={15} /> },
  { id: "memory", labelKey: "nav.memory", icon: <Brain size={15} /> },
  { id: "usage", labelKey: "nav.usage", icon: <Coins size={15} /> },
  { id: "settings", labelKey: "nav.settings", icon: <Settings size={15} /> },
];

function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const { t } = useTranslation();
  return (
    <button
      onClick={toggleTheme}
      aria-label={theme === "dark" ? t("nav.switchToLight") : t("nav.switchToDark")}
      title={theme === "dark" ? t("nav.switchToLight") : t("nav.switchToDark")}
      className={cn(
        "p-1.5 rounded-lg transition-colors",
        "text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]",
      )}
    >
      {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
    </button>
  );
}

function LanguageSwitcher({ sessionId }: { sessionId?: string | null }) {
  const { i18n, t } = useTranslation();
  const [showConfirm, setShowConfirm] = useState(false);
  const [pendingLang, setPendingLang] = useState<LanguageCode>("en");

  const currentLang = i18n.language;

  const handleLangClick = (code: LanguageCode) => {
    if (code === currentLang) return;
    setPendingLang(code);
    setShowConfirm(true);
  };

  const handleConfirm = async () => {
    i18n.changeLanguage(pendingLang);
    localStorage.setItem("crabagent-language", pendingLang);
    // Notify backend: update both AppSetting and User.locale
    try {
      const { updateSettings } = await import("../api/settings");
      await updateSettings({ language: pendingLang });
    } catch (e) {
      console.error("[i18n] Failed to update settings:", e);
    }
    try {
      const { api } = await import("../api/client");
      await api.patch("/auth/user", { locale: pendingLang });
    } catch (e) {
      console.error("[i18n] Failed to update user locale:", e);
    }
    // Reset cached system prompt for current session so next message uses new locale
    if (sessionId) {
      try {
        const { api } = await import("../api/client");
        await api.post(`/sessions/${sessionId}/reset-system-prompt`, {});
      } catch (e) {
        console.error("[i18n] Failed to reset system prompt:", e);
      }
    }
    setShowConfirm(false);
  };

  return (
    <>
      <button
        className={cn(
          "flex items-center gap-0.5 p-1.5 rounded-lg transition-colors",
          "text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]",
        )}
        title={t("language.title")}
        onClick={() => {
          // Quick cycle through languages
          const idx = SUPPORTED_LANGUAGES.findIndex((l) => l.code === currentLang);
          const next = SUPPORTED_LANGUAGES[(idx + 1) % SUPPORTED_LANGUAGES.length];
          handleLangClick(next.code);
        }}
      >
        <Globe size={15} />
        <span className="text-[10px] font-semibold ml-0.5 text-[var(--text-tertiary)]">
          {currentLang === "zh-CN" ? "中" : "EN"}
        </span>
      </button>

      <Modal
        open={showConfirm}
        onOpenChange={setShowConfirm}
        title={t("language.switchTitle")}
        description={t("language.switchDesc")}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setShowConfirm(false)}>
              {t("common.cancel")}
            </Button>
            <Button variant="brand" onClick={handleConfirm}>
              {t("language.switchConfirm")}
            </Button>
          </>
        }
      >
        <div className="text-sm text-[var(--text-secondary)]">
          {SUPPORTED_LANGUAGES.find((l) => l.code === pendingLang)?.label}
          <p className="mt-2 text-xs text-[var(--text-tertiary)]">
            {t("language.currentSession")}
          </p>
        </div>
      </Modal>
    </>
  );
}

export function NavBar({
  currentPage,
  onNavigate,
  onLogout,
  sessionId,
}: {
  currentPage: PageId;
  onNavigate: (page: PageId) => void;
  onLogout?: () => void;
  sessionId?: string | null;
}) {
  const { t } = useTranslation();
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);

  return (
    <header
      className={cn(
        "sticky top-0 z-30 flex items-center gap-1 px-4 sm:px-6 h-12",
        "backdrop-blur-md bg-[var(--bg-secondary)]/80",
        "border-b border-[var(--border)]",
      )}
      style={{ paddingTop: "env(safe-area-inset-top, 0px)" }}
    >
      <button
        onClick={() => onNavigate("chat")}
        className="flex items-center gap-2 mr-1 sm:mr-4 group"
      >
        <span
          className="w-7 h-7 rounded-lg flex items-center justify-center text-base shadow-[var(--shadow-sm)]"
          style={{
            background:
              "linear-gradient(135deg, var(--brand) 0%, var(--brand-active) 100%)",
          }}
        >
          🦀
        </span>
        <span className="font-semibold text-sm text-[var(--text-primary)] group-hover:text-[var(--brand)] transition-colors">
          CrabAgent
        </span>
      </button>

      <nav className="flex items-center gap-0.5">
        {items.map((item) => {
          const isActive = currentPage === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all relative",
                isActive
                  ? "text-[var(--text-primary)] bg-[var(--bg-tertiary)]"
                  : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]/60",
              )}
            >
              <span className={cn(isActive && "text-[var(--brand)]")}>
                {item.icon}
              </span>
              <span className="hidden sm:inline">{t(item.labelKey)}</span>
              {isActive && (
                <span className="absolute -bottom-[9px] left-1/2 -translate-x-1/2 w-1 h-1 rounded-full bg-[var(--brand)]" />
              )}
            </button>
          );
        })}
      </nav>

      <div className="ml-auto flex items-center gap-1">
        {onLogout && (
          <button
            onClick={() => setShowLogoutConfirm(true)}
            aria-label={t("nav.logout")}
            title={t("nav.logout")}
            className={cn(
              "p-1.5 rounded-lg transition-colors",
              "text-[var(--text-tertiary)] hover:text-[var(--danger)] hover:bg-[var(--danger-bg)]",
            )}
          >
            <LogOut size={15} />
          </button>
        )}
        <LanguageSwitcher sessionId={sessionId} />
        <ThemeToggle />
      </div>

      {onLogout && (
        <Modal
          open={showLogoutConfirm}
          onOpenChange={setShowLogoutConfirm}
          title={t("nav.signOut")}
          description={t("nav.signOutDesc")}
          size="sm"
          footer={
            <>
              <Button variant="ghost" onClick={() => setShowLogoutConfirm(false)}>
                {t("common.cancel")}
              </Button>
              <Button variant="danger" onClick={onLogout}>
                {t("nav.signOutBtn")}
              </Button>
            </>
          }
        >
          <div className="text-center py-2">
            <LogOut size={32} className="mx-auto text-[var(--danger)] mb-2" />
          </div>
        </Modal>
      )}
    </header>
  );
}

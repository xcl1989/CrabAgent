import { MessageSquare, Users, Brain, Sun, Moon, LogOut } from "lucide-react";
import { useTheme } from "../lib/theme";
import { cn } from "../lib/cn";
import { useState } from "react";
import { Modal, Button } from "./ui";
import type { PageId } from "../App";

interface NavItem {
  id: PageId;
  label: string;
  icon: React.ReactNode;
}

const items: NavItem[] = [
  { id: "chat", label: "Chat", icon: <MessageSquare size={15} /> },
  { id: "agents", label: "Agents", icon: <Users size={15} /> },
  { id: "memory", label: "Memory", icon: <Brain size={15} /> },
];

function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  return (
    <button
      onClick={toggleTheme}
      aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
      title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
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

export function NavBar({
  currentPage,
  onNavigate,
  onLogout,
}: {
  currentPage: PageId;
  onNavigate: (page: PageId) => void;
  onLogout?: () => void;
}) {
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
              <span className="hidden sm:inline">{item.label}</span>
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
            aria-label="Logout"
            title="Logout"
            className={cn(
              "p-1.5 rounded-lg transition-colors",
              "text-[var(--text-tertiary)] hover:text-[var(--danger)] hover:bg-[var(--danger-bg)]",
            )}
          >
            <LogOut size={15} />
          </button>
        )}
        <ThemeToggle />
      </div>

      {onLogout && (
        <Modal
          open={showLogoutConfirm}
          onOpenChange={setShowLogoutConfirm}
          title="Sign out?"
          description="You'll need to log in again to continue."
          size="sm"
          footer={
            <>
              <Button variant="ghost" onClick={() => setShowLogoutConfirm(false)}>
                Cancel
              </Button>
              <Button variant="danger" onClick={onLogout}>
                Sign Out
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

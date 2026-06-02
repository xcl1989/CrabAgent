import { NavLink } from "react-router-dom";
import { MessageSquare, LayoutDashboard, Users, Sun, Moon } from "lucide-react";
import { useTheme } from "../lib/theme";
import { cn } from "../lib/cn";

interface NavItem {
  to: string;
  label: string;
  icon: React.ReactNode;
}

const items: NavItem[] = [
  { to: "/chat", label: "Chat", icon: <MessageSquare size={15} /> },
  {
    to: "/dashboard",
    label: "Dashboard",
    icon: <LayoutDashboard size={15} />,
  },
  { to: "/agents", label: "Agents", icon: <Users size={15} /> },
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

export function NavBar() {
  return (
    <header
      className={cn(
        "sticky top-0 z-30 flex items-center gap-1 px-4 sm:px-6 h-12",
        "backdrop-blur-md bg-[var(--bg-secondary)]/80",
        "border-b border-[var(--border)]",
      )}
    >
      {/* Brand */}
      <NavLink to="/chat" className="flex items-center gap-2 mr-4 group">
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
      </NavLink>

      {/* Nav items */}
      <nav className="flex items-center gap-0.5">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/chat"}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all relative",
                isActive
                  ? "text-[var(--text-primary)] bg-[var(--bg-tertiary)]"
                  : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]/60",
              )
            }
          >
            {({ isActive }) => (
              <>
                <span className={cn(isActive && "text-[var(--brand)]")}>
                  {item.icon}
                </span>
                <span>{item.label}</span>
                {isActive && (
                  <span className="absolute -bottom-[9px] left-1/2 -translate-x-1/2 w-1 h-1 rounded-full bg-[var(--brand)]" />
                )}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="ml-auto flex items-center gap-1">
        <ThemeToggle />
      </div>
    </header>
  );
}

import { NavLink } from "react-router-dom";

export function NavBar() {
  return (
    <nav
      className="flex items-center gap-1 px-4 py-2"
      style={{ borderBottom: "1px solid var(--border)", background: "var(--bg-secondary)" }}
    >
      <span className="font-semibold text-sm mr-4" style={{ color: "var(--accent)" }}>
        CrabAgent
      </span>
      <NavLink
        to="/chat"
        end
        className={({ isActive }) =>
          `px-3 py-1.5 rounded-md text-sm ${isActive ? "font-medium" : ""}`
        }
        style={({ isActive }) => ({
          background: isActive ? "var(--accent-bg)" : "transparent",
          color: isActive ? "var(--accent)" : "var(--text-secondary)",
        })}
      >
        Chat
      </NavLink>
      <NavLink
        to="/dashboard"
        className={({ isActive }) =>
          `px-3 py-1.5 rounded-md text-sm ${isActive ? "font-medium" : ""}`
        }
        style={({ isActive }) => ({
          background: isActive ? "var(--accent-bg)" : "transparent",
          color: isActive ? "var(--accent)" : "var(--text-secondary)",
        })}
      >
        Dashboard
      </NavLink>
      <NavLink
        to="/agents"
        className={({ isActive }) =>
          `px-3 py-1.5 rounded-md text-sm ${isActive ? "font-medium" : ""}`
        }
        style={({ isActive }) => ({
          background: isActive ? "var(--accent-bg)" : "transparent",
          color: isActive ? "var(--accent)" : "var(--text-secondary)",
        })}
      >
        Agents
      </NavLink>
    </nav>
  );
}

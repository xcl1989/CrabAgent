import { useState } from "react";
import {
  Plus,
  Trash2,
  ChevronLeft,
  Search,
  Plug,
  Clock,
  Bot,
  Settings as SettingsIcon,
  GitBranch,
  MessageSquare,
} from "lucide-react";
import { Session } from "../api/sessions";
import { formatDate } from "../api/time";
import { Button, EmptyState, ConfirmDialog } from "./ui";
import { cn } from "../lib/cn";

interface Props {
  sessions: Session[];
  activeId: string | null;
  onSelect: (session: Session) => void;
  onNew: () => void;
  onDelete: (sessionId: string) => void;
  onOpenProviders: () => void;
  onOpenMcpServers: () => void;
  onOpenScheduledTasks: () => void;
  onOpenAgentTeam: () => void;
}

export default function SessionList({
  sessions,
  activeId,
  onSelect,
  onNew,
  onDelete,
  onOpenProviders,
  onOpenMcpServers,
  onOpenScheduledTasks,
  onOpenAgentTeam,
}: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const [query, setQuery] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Session | null>(null);

  const filtered = query.trim()
    ? sessions.filter((s) =>
        (s.title || "").toLowerCase().includes(query.toLowerCase()),
      )
    : sessions;

  const handleDelete = () => {
    if (deleteTarget) onDelete(deleteTarget.session_id);
    setDeleteTarget(null);
  };

  if (collapsed) {
    const ToolButton = ({
      onClick,
      icon,
      title,
      color,
    }: {
      onClick: () => void;
      icon: React.ReactNode;
      title: string;
      color: string;
    }) => (
      <button
        onClick={onClick}
        title={title}
        className={cn(
          "p-2 rounded-lg transition-colors",
          "text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
        )}
        style={{ color }}
      >
        {icon}
      </button>
    );
    return (
      <div
        className="hidden md:flex flex-col items-center py-3 gap-1 border-r border-[var(--border)] bg-[var(--bg-secondary)] shrink-0"
        style={{ width: 56 }}
      >
        <button
          onClick={() => setCollapsed(false)}
          title="Expand sidebar"
          className="p-2 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
        >
          <MessageSquare size={16} />
        </button>
        <Button
          size="icon"
          variant="brand"
          onClick={onNew}
          title="New session (⌘K)"
          className="my-1"
        >
          <Plus size={16} />
        </Button>
        <div className="flex-1" />
        <ToolButton
          onClick={onOpenMcpServers}
          icon={<Plug size={15} />}
          title="MCP Servers"
          color=""
        />
        <ToolButton
          onClick={onOpenScheduledTasks}
          icon={<Clock size={15} />}
          title="Scheduled Tasks"
          color=""
        />
        <ToolButton
          onClick={onOpenAgentTeam}
          icon={<Bot size={15} />}
          title="Agent Team"
          color=""
        />
        <ToolButton
          onClick={onOpenProviders}
          icon={<SettingsIcon size={15} />}
          title="Providers"
          color=""
        />
      </div>
    );
  }

  return (
    <div
      className="hidden md:flex flex-col border-r border-[var(--border)] bg-[var(--bg-secondary)] shrink-0 w-64 lg:w-72"
    >
      {/* Header */}
      <div className="p-2.5 flex items-center gap-2 border-b border-[var(--border-subtle)]">
        <span className="text-sm font-semibold text-[var(--text-primary)] flex-1">
          Conversations
        </span>
        <Button
          size="icon"
          variant="brand"
          onClick={onNew}
          title="New session (⌘K)"
        >
          <Plus size={14} />
        </Button>
        <button
          onClick={() => setCollapsed(true)}
          title="Collapse sidebar"
          className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
        >
          <ChevronLeft size={14} />
        </button>
      </div>

      {/* Search */}
      {sessions.length > 4 && (
        <div className="p-2 border-b border-[var(--border-subtle)]">
          <div className="relative">
            <Search
              size={13}
              className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]"
            />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search…"
              className="w-full h-7 pl-7 pr-2 text-xs rounded-md bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--brand)] focus:ring-2 focus:ring-[var(--brand)]/30"
            />
          </div>
        </div>
      )}

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {sessions.length === 0 ? (
          <EmptyState
            compact
            icon={<MessageSquare size={24} />}
            title="No conversations"
            description="Start a new session to begin."
          />
        ) : filtered.length === 0 ? (
          <div className="p-4 text-xs text-center text-[var(--text-tertiary)]">
            No matches
          </div>
        ) : (
          filtered.map((s) => {
            const isActive = activeId === s.session_id;
            return (
              <div
                key={s.session_id}
                onClick={() => onSelect(s)}
                className={cn(
                  "group relative px-3 py-2 cursor-pointer transition-colors",
                  "border-l-2",
                  isActive
                    ? "bg-[var(--bg-tertiary)] border-l-[var(--brand)]"
                    : "border-l-transparent hover:bg-[var(--bg-tertiary)]/60",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div
                      className={cn(
                        "truncate text-sm flex items-center gap-1.5",
                        isActive
                          ? "text-[var(--text-primary)] font-medium"
                          : "text-[var(--text-secondary)]",
                      )}
                    >
                      <span className="truncate">
                        {s.title || "(untitled)"}
                      </span>
                      {s.active_branch && s.active_branch !== "main" && (
                        <span className="inline-flex items-center gap-0.5 text-[9px] px-1 py-px rounded font-mono bg-[var(--warning-bg)] text-[var(--warning)] shrink-0">
                          <GitBranch size={9} />
                          {s.active_branch}
                        </span>
                      )}
                    </div>
                    <div className="text-[10px] mt-0.5 text-[var(--text-tertiary)] font-mono">
                      {formatDate(s.updated_at)}
                    </div>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setDeleteTarget(s);
                    }}
                    title="Delete session"
                    className={cn(
                      "shrink-0 p-1 rounded transition-all",
                      "opacity-0 group-hover:opacity-100",
                      "text-[var(--text-tertiary)] hover:text-[var(--danger)] hover:bg-[var(--danger-bg)]",
                    )}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Footer tools */}
      <div className="p-2 border-t border-[var(--border-subtle)] grid grid-cols-2 gap-1">
        <button
          onClick={onOpenMcpServers}
          className={cn(
            "flex items-center gap-1.5 px-2 py-1.5 rounded-md text-[11px] font-medium",
            "bg-[var(--bg-tertiary)] border border-[var(--border)]",
            "hover:border-[var(--border-strong)] hover:text-[var(--text-primary)] transition-colors",
            "text-[var(--text-secondary)]",
          )}
          title="MCP Servers"
        >
          <Plug size={12} className="text-[var(--accent-2)]" />
          <span>MCP</span>
        </button>
        <button
          onClick={onOpenScheduledTasks}
          className={cn(
            "flex items-center gap-1.5 px-2 py-1.5 rounded-md text-[11px] font-medium",
            "bg-[var(--bg-tertiary)] border border-[var(--border)]",
            "hover:border-[var(--border-strong)] hover:text-[var(--text-primary)] transition-colors",
            "text-[var(--text-secondary)]",
          )}
          title="Scheduled Tasks"
        >
          <Clock size={12} className="text-[var(--warning)]" />
          <span>Tasks</span>
        </button>
        <button
          onClick={onOpenAgentTeam}
          className={cn(
            "flex items-center gap-1.5 px-2 py-1.5 rounded-md text-[11px] font-medium",
            "bg-[var(--bg-tertiary)] border border-[var(--border)]",
            "hover:border-[var(--border-strong)] hover:text-[var(--text-primary)] transition-colors",
            "text-[var(--text-secondary)]",
          )}
          title="Agent Team"
        >
          <Bot size={12} className="text-[var(--accent-2)]" />
          <span>Team</span>
        </button>
        <button
          onClick={onOpenProviders}
          className={cn(
            "flex items-center gap-1.5 px-2 py-1.5 rounded-md text-[11px] font-medium",
            "bg-[var(--bg-tertiary)] border border-[var(--border)]",
            "hover:border-[var(--border-strong)] hover:text-[var(--text-primary)] transition-colors",
            "text-[var(--text-secondary)]",
          )}
          title="Providers"
        >
          <SettingsIcon size={12} className="text-[var(--text-tertiary)]" />
          <span>API Keys</span>
        </button>
      </div>

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        title={`Delete conversation "${deleteTarget?.title || "untitled"}"?`}
        description="This permanently removes the session and its message history."
        confirmText="Delete"
        tone="danger"
        onConfirm={handleDelete}
      />
    </div>
  );
}

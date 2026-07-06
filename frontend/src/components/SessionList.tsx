import { useState, useEffect, useRef, useMemo } from "react";
import {
  Plus,
  Trash2,
  ChevronLeft,
  Search,
  Plug,
  Clock,
  Settings as SettingsIcon,
  GitBranch,
  MessageSquare,
  X as XIcon,
  ListTodo,
  Mail,
  Zap,
  BarChart3,
  Bell,
  Inbox,
  Sparkles,
  Loader2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Session, SearchResult, searchSessions } from "../api/sessions";
import { AgentMonitorInfo } from "../api/monitor";
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
  onOpenTasks: () => void;
  onOpenEmail: () => void;
  onOpenSkills: () => void;
  onQuickAction?: (action: "digest" | "remind" | "inbox") => void;
  mobileOpen?: boolean;
  onMobileClose?: () => void;
  workspace?: string;
  activeMonitors?: AgentMonitorInfo[];
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
  onOpenTasks,
  onOpenEmail,
  onOpenSkills,
  onQuickAction,
  mobileOpen = false,
  onMobileClose,
  workspace,
  activeMonitors = [],
}: Props) {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(false);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Session | null>(null);
  const [quickMenuOpen, setQuickMenuOpen] = useState(false);
  const quickMenuRef = useRef<HTMLDivElement>(null);

  // Set of session_ids that are currently running
  const runningIds = useMemo(() => {
    const ids = new Set<string>();
    for (const m of activeMonitors) {
      if (m.status === "running") ids.add(m.session_id);
    }
    return ids;
  }, [activeMonitors]);

  // Auto-close mobile drawer when a session is selected
  useEffect(() => {
    if (mobileOpen && onMobileClose) {
      const handler = (e: KeyboardEvent) => {
        if (e.key === "Escape") onMobileClose();
      };
      window.addEventListener("keydown", handler);
      return () => window.removeEventListener("keydown", handler);
    }
  }, [mobileOpen, onMobileClose]);

  // Close quick menu on outside click
  useEffect(() => {
    if (!quickMenuOpen) return;
    const handler = (e: MouseEvent) => {
      if (quickMenuRef.current && !quickMenuRef.current.contains(e.target as Node)) {
        setQuickMenuOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setQuickMenuOpen(false);
    };
    document.addEventListener("mousedown", handler);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("keydown", onKey);
    };
  }, [quickMenuOpen]);

  // ── Debounced full-text search via API ────────────────
  useEffect(() => {
    if (!query.trim()) {
      setSearchResults(null);
      setSearchLoading(false);
      return;
    }
    setSearchLoading(true);
    const timer = setTimeout(async () => {
      try {
        const results = await searchSessions(query.trim(), workspace);
        setSearchResults(results);
      } catch {
        setSearchResults([]);
      }
      setSearchLoading(false);
    }, 300);
    return () => { clearTimeout(timer); setSearchLoading(false); };
  }, [query]);

  const filtered = useMemo(() => query.trim()
    ? sessions.filter((s) =>
        (s.title || "").toLowerCase().includes(query.toLowerCase()),
      )
    : sessions, [sessions, query]);

  const handleSelect = (s: Session) => {
    onSelect(s);
    if (onMobileClose) onMobileClose();
  };

  const handleNew = () => {
    onNew();
    if (onMobileClose) onMobileClose();
  };

  const handleDelete = () => {
    if (deleteTarget) onDelete(deleteTarget.session_id);
    setDeleteTarget(null);
  };

  if (collapsed) {
    const ToolButton = ({
      onClick,
      icon,
      title,
    }: {
      onClick: () => void;
      icon: React.ReactNode;
      title: string;
    }) => (
      <button
        onClick={onClick}
        title={title}
        className={cn(
          "p-2 rounded-lg transition-colors",
          "text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
        )}
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
          title={t("session.expandSidebar")}
          className="p-2 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
        >
          <MessageSquare size={16} />
        </button>
        <Button
          size="icon"
          variant="brand"
          onClick={handleNew}
          title={`${t("session.newChat")} (⌘K)`}
          className="my-1"
        >
          <Plus size={16} />
        </Button>
        <div className="flex-1" />
        <ToolButton onClick={onOpenSkills} icon={<Sparkles size={15} />} title="Skills" />
        <ToolButton onClick={onOpenMcpServers} icon={<Plug size={15} />} title={t("mcp.title")} />
        <ToolButton onClick={onOpenScheduledTasks} icon={<Clock size={15} />} title={t("scheduledTask.title")} />
        <ToolButton onClick={onOpenProviders} icon={<SettingsIcon size={15} />} title={t("provider.title")} />
      </div>
    );
  }

  const sidebar = (
    <div
      className={cn(
        "flex flex-col h-full bg-[var(--bg-secondary)] w-64 lg:w-72",
        "md:border-r md:border-[var(--border)] md:shrink-0",
      )}
    >
      {/* Mobile header */}
      <div className="md:hidden p-2.5 flex items-center gap-2 border-b border-[var(--border-subtle)]">
        <span className="text-sm font-semibold text-[var(--text-primary)] flex-1">
          {t("session.sessions")}
        </span>
        <button
          onClick={onMobileClose}
          title={t("common.close")}
          className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
        >
          <XIcon size={14} />
        </button>
      </div>
      {/* Desktop header */}
      <div className="hidden md:flex p-2.5 items-center gap-2 border-b border-[var(--border-subtle)]">
        <span className="text-sm font-semibold text-[var(--text-primary)] flex-1">
          {t("session.sessions")}
        </span>
        <Button
          size="icon"
          variant="brand"
          onClick={handleNew}
          title={`${t("session.newChat")} (⌘K)`}
        >
          <Plus size={14} />
        </Button>
        <button
          onClick={() => setCollapsed(true)}
          title={t("session.collapseSidebar")}
          className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
        >
          <ChevronLeft size={14} />
        </button>
      </div>

      {/* Search */}
      {sessions.length > 2 && (
        <div className="p-2 border-b border-[var(--border-subtle)]">
          <div className="relative">
            <Search
              size={13}
              className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]"
            />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("session.searchPlaceholder")}
              className="w-full h-7 pl-7 pr-2 text-xs rounded-md bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--brand)] focus:ring-2 focus:ring-[var(--brand)]/30"
            />
          </div>
        </div>
      )}

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {searchResults !== null ? (
          /* ── Search results ── */
          searchResults.length === 0 ? (
            <div className="p-4 text-xs text-center text-[var(--text-tertiary)]">
              {t("common.noResults")}
            </div>
          ) : (
            searchResults.map((r) => {
              const isActive = activeId === r.session_id;
              return (
                <div
                  key={r.session_id}
                  onClick={() => {
                    const session = sessions.find((s) => s.session_id === r.session_id);
                    if (session) {
                      handleSelect(session);
                    } else {
                      // Session not in current list — construct minimal object
                      handleSelect({
                        session_id: r.session_id,
                        title: r.title || "",
                        workspace: workspace || "",
                        model: "",
                        provider: "",
                        agent: "default",
                        active_branch: "main",
                        prompt_locale: "",
                        created_at: null,
                        updated_at: r.updated_at,
                      });
                    }
                  }}
                  className={cn(
                    "group relative px-3 py-2 cursor-pointer transition-colors",
                    "border-l-2",
                    isActive
                      ? "bg-[var(--bg-tertiary)] border-l-[var(--brand)]"
                      : "border-l-transparent hover:bg-[var(--bg-tertiary)]/60",
                  )}
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm text-[var(--text-primary)] flex items-center gap-1.5">
                      <span className="truncate">{r.title || `(${t("session.untitled")})`}</span>
                      <span className={cn(
                        "inline-flex items-center px-1 py-px rounded text-[9px] font-medium shrink-0",
                        r.role === "user" ? "bg-[var(--brand-bg)] text-[var(--brand)]" : "bg-[var(--accent-bg)] text-[var(--accent)]",
                      )}>
                        {r.role === "user" ? "问" : "答"}
                      </span>
                    </div>
                    {r.snippet && (
                      <div className="text-[11px] mt-0.5 text-[var(--text-tertiary)] leading-relaxed line-clamp-2">
                        {r.snippet}
                      </div>
                    )}
                    <div className="text-[10px] mt-0.5 text-[var(--text-tertiary)] font-mono">
                      {r.updated_at ? formatDate(r.updated_at) : ""}
                    </div>
                  </div>
                </div>
              );
            })
          )
        ) : sessions.length === 0 ? (
          <EmptyState
            compact
            icon={<MessageSquare size={24} />}
            title={t("common.noResults")}
            description=""
          />
        ) : filtered.length === 0 ? (
          <div className="p-4 text-xs text-center text-[var(--text-tertiary)]">
            {t("common.noResults")}
          </div>
        ) : (
          filtered.map((s) => {
            const isActive = activeId === s.session_id;
            return (
              <div
                key={s.session_id}
                onClick={() => handleSelect(s)}
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
                      {runningIds.has(s.session_id) && (
                        <span
                          className="inline-block w-1.5 h-1.5 rounded-full shrink-0 animate-pulse"
                          style={{ background: "var(--success)" }}
                          title="运行中"
                        />
                      )}
                      <span className="truncate">
                        {s.title || `(${t("session.untitled")})`}
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
                    title={t("session.deleteSession")}
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

      {/* Footer toolbar */}
      <div className="px-3 py-2 border-t border-[var(--border-subtle)] flex items-center relative">
        {/* Quick action trigger */}
        {onQuickAction && (
          <div ref={quickMenuRef} className="relative">
            <button
              onClick={() => setQuickMenuOpen((v) => !v)}
              className={cn(
                "p-1.5 rounded-lg transition-colors",
                quickMenuOpen
                  ? "text-[var(--brand)] bg-[var(--brand-bg)]"
                  : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
              )}
              title={t("quickAction.title", "Quick actions")}
            >
              <Zap size={15} />
            </button>
            {quickMenuOpen && (
              <div className="absolute bottom-full left-0 mb-1 w-40 rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] shadow-[var(--shadow-lg)] py-1 animate-scale-in origin-bottom-left z-50">
                <button
                  onClick={() => { onQuickAction("digest"); setQuickMenuOpen(false); }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)] transition-colors"
                >
                  <BarChart3 size={13} className="text-[var(--brand)]" />
                  {t("quickAction.digest")}
                </button>
                <button
                  onClick={() => { onQuickAction("remind"); setQuickMenuOpen(false); }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)] transition-colors"
                >
                  <Bell size={13} className="text-[var(--warning)]" />
                  {t("quickAction.remind")}
                </button>
                <button
                  onClick={() => { onQuickAction("inbox"); setQuickMenuOpen(false); }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)] transition-colors"
                >
                  <Inbox size={13} className="text-[var(--accent)]" />
                  {t("quickAction.inbox")}
                </button>
              </div>
            )}
          </div>
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Tool icons — unified hover style */}
        <div className="flex items-center gap-0.5">
          <button
            onClick={onOpenTasks}
            title={t("task.title")}
            className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
          >
            <ListTodo size={15} />
          </button>
          <button
            onClick={onOpenEmail}
            title={t("email.title")}
            className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
          >
            <Mail size={15} />
          </button>
          <button
            onClick={onOpenMcpServers}
            title={t("mcp.title")}
            className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
          >
            <Plug size={15} />
          </button>
          <button
            onClick={onOpenSkills}
            title="Skills"
            className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
          >
            <Sparkles size={15} />
          </button>
          <button
            onClick={onOpenScheduledTasks}
            title={t("scheduledTask.title")}
            className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
          >
            <Clock size={15} />
          </button>
          <button
            onClick={onOpenProviders}
            title={t("provider.title")}
            className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
          >
            <SettingsIcon size={15} />
          </button>
        </div>
      </div>

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        title={t("session.deleteConfirm", { title: deleteTarget?.title || t("session.untitled") })}
        description=""
        confirmText={t("common.delete")}
        tone="danger"
        onConfirm={handleDelete}
      />
    </div>
  );

  return (
    <>
      {!mobileOpen && (
        <div className="hidden md:contents">{sidebar}</div>
      )}
      {mobileOpen && (
        <>
          <div
            className="md:hidden fixed inset-0 z-40 bg-[var(--bg-overlay)] backdrop-blur-sm animate-fade-in"
            onClick={onMobileClose}
          />
          <div className="md:hidden fixed top-0 left-0 bottom-0 z-50 w-72 max-w-[85vw] animate-slide-up shadow-[var(--shadow-lg)]">
            {sidebar}
          </div>
        </>
      )}
    </>
  );
}

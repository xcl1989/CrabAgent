import { useEffect, useState, useRef } from "react";
import { Bell } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  listNotifications,
  unreadCount,
  markRead,
  markAllRead,
  Notification,
} from "../api/notifications";
import { cn } from "../lib/cn";

interface Props {
  onSwitchSession: (sessionId: string) => void;
}

type Tab = "unread" | "read";

function relativeTime(d: string | null | undefined): string {
  if (!d) return "";
  const date = new Date(d);
  const diff = Date.now() - date.getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return date.toLocaleDateString();
}

export default function NotificationBell({ onSwitchSession }: Props) {
  const { t } = useTranslation();
  const [count, setCount] = useState(0);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("unread");
  const ref = useRef<HTMLDivElement>(null);

  const fetchUnread = async () => {
    try {
      const res = await unreadCount();
      setCount(res.count);
    } catch {
      /* ignore */
    }
  };

  const fetchList = async () => {
    try {
      setNotifications(await listNotifications());
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    fetchUnread();
    const interval = setInterval(fetchUnread, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (open) fetchList();
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    if (open) {
      document.addEventListener("mousedown", handler);
      document.addEventListener("keydown", onKey);
    }
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const handleClick = async (n: Notification) => {
    if (!n.read) {
      await markRead(n.id);
      setCount((c) => Math.max(0, c - 1));
    }
    setOpen(false);
    if (n.conversation_id) onSwitchSession(n.conversation_id);
  };

  const handleMarkAll = async () => {
    await markAllRead();
    setCount(0);
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
  };

  const unreadItems = notifications.filter((n) => !n.read);
  const readItems = notifications.filter((n) => n.read);
  const displayItems = tab === "unread" ? unreadItems : readItems;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "relative p-1.5 rounded-lg transition-colors",
          "text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]",
        )}
        title={t("notification.title")}
        aria-label={`${t("notification.title")}${count > 0 ? ` (${count} ${t("notification.unread").toLowerCase()})` : ""}`}
      >
        <Bell size={15} />
        {count > 0 && (
          <span
            className="absolute -top-0.5 -right-0.5 text-[9px] font-bold min-w-[16px] h-4 px-1 rounded-full flex items-center justify-center bg-[var(--danger)] text-white animate-scale-in">
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>
      {open && (
        <div
          className={cn(
            "absolute right-0 top-full mt-1 w-80 rounded-xl flex flex-col z-50",
            "bg-[var(--bg-elevated)] border border-[var(--border)]",
            "shadow-[var(--shadow-lg)] animate-scale-in origin-top-right",
          )}
          style={{ maxHeight: "440px" }}
        >
          <div className="flex items-center shrink-0 border-b border-[var(--border-subtle)]">
            {(["unread", "read"] as Tab[]).map((tabKey) => {
              const isActive = tab === tabKey;
              const label = tabKey === "unread"
                  ? `${t("notification.unread")}${unreadItems.length > 0 ? ` (${unreadItems.length})` : ""}`
                  : `${t("notification.read")}${readItems.length > 0 ? ` (${readItems.length})` : ""}`;
              return (
                <button
                  key={tabKey}
                  onClick={() => setTab(tabKey)}
                  className={cn(
                    "flex-1 px-3 py-2 text-xs font-medium transition-colors relative",
                    isActive
                      ? "text-[var(--text-primary)]"
                      : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]",
                  )}
                >
                  {label}
                  {isActive && (
                    <span className="absolute bottom-0 left-2 right-2 h-0.5 rounded-full bg-[var(--brand)]" />
                  )}
                </button>
              );
            })}
            {unreadItems.length > 0 && (
              <button
                onClick={handleMarkAll}
                className="px-3 py-2 text-[10px] shrink-0 text-[var(--brand)] hover:underline"
              >
                {t("notification.markAll")}
              </button>
            )}
          </div>
          <div className="flex-1 overflow-y-auto">
            {displayItems.length === 0 ? (
              <div className="px-4 py-8 text-center text-xs text-[var(--text-tertiary)]">
                {tab === "unread"
                  ? t("notification.noUnread")
                  : t("notification.noRead")}
              </div>
            ) : (
              displayItems.slice(0, 20).map((n) => (
                <div
                  key={n.id}
                  onClick={() => handleClick(n)}
                  className={cn(
                    "px-3 py-2.5 cursor-pointer transition-colors border-l-2",
                    "hover:bg-[var(--bg-tertiary)]",
                    !n.read
                      ? "border-l-[var(--brand)] bg-[var(--brand-bg)]/30"
                      : "border-l-transparent",
                  )}
                >
                  <div className="flex items-center gap-2">
                    {!n.read && (
                      <span className="w-1.5 h-1.5 rounded-full bg-[var(--brand)] shrink-0" />
                    )}
                    <span
                      className={cn(
                        "text-xs flex-1 truncate",
                        n.read
                          ? "text-[var(--text-tertiary)] font-normal"
                          : "text-[var(--text-primary)] font-semibold",
                      )}
                    >
                      {n.title}
                    </span>
                  </div>
                  <div
                    className={cn(
                      "text-[11px] mt-0.5 truncate ml-3.5",
                      n.read ? "text-[var(--text-tertiary)]" : "text-[var(--text-secondary)]",
                    )}
                  >
                    {n.body}
                  </div>
                  <div className="text-[10px] mt-1 ml-3.5 text-[var(--text-tertiary)] font-mono">
                    {relativeTime(n.created_at)}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

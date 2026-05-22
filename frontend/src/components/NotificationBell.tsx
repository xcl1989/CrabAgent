import { useEffect, useState, useRef } from "react";
import { listNotifications, unreadCount, markRead, markAllRead, Notification } from "../api/notifications";

interface Props {
  onSwitchSession: (sessionId: string) => void;
}

export function NotificationBell({ onSwitchSession }: Props) {
  const [count, setCount] = useState(0);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const fetchUnread = async () => {
    try {
      const res = await unreadCount();
      setCount(res.count);
    } catch { /* ignore */ }
  };

  const fetchList = async () => {
    try {
      const list = await listNotifications();
      setNotifications(list);
    } catch { /* ignore */ }
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
    if (open) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
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

  return (
    <div ref={ref} className="relative" style={{ zIndex: 50 }}>
      <button
        onClick={() => setOpen(!open)}
        className="relative p-1.5 rounded hover:opacity-80 transition-opacity"
        style={{ background: "transparent" }}
        title="通知"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        </svg>
        {count > 0 && (
          <span
            className="absolute -top-0.5 -right-0.5 text-[10px] font-bold w-4 h-4 rounded-full flex items-center justify-center"
            style={{ background: "#ef4444", color: "#fff" }}
          >
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>
      {open && (
        <div
          className="absolute right-0 top-full mt-1 w-80 max-h-96 overflow-y-auto rounded-xl shadow-2xl"
          style={{ background: "var(--bg-primary)", border: "1px solid var(--border)" }}
        >
          <div className="flex items-center justify-between px-4 py-2.5" style={{ borderBottom: "1px solid var(--border)" }}>
            <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>通知</span>
            {notifications.some((n) => !n.read) && (
              <button onClick={handleMarkAll} className="text-xs" style={{ color: "var(--accent)" }}>
                全部已读
              </button>
            )}
          </div>
          {notifications.length === 0 ? (
            <div className="px-4 py-6 text-center text-xs" style={{ color: "var(--text-secondary)" }}>暂无通知</div>
          ) : (
            notifications.slice(0, 20).map((n) => (
              <div
                key={n.id}
                onClick={() => handleClick(n)}
                className="px-4 py-3 cursor-pointer transition-colors hover:opacity-80"
                style={{
                  borderBottom: "1px solid var(--border)",
                  background: n.read ? "transparent" : "var(--bg-tertiary)",
                }}
              >
                <div className="flex items-center gap-2">
                  {!n.read && <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: "var(--accent)" }} />}
                  <span className="text-sm font-medium truncate" style={{ color: "var(--text-primary)" }}>{n.title}</span>
                </div>
                <div className="text-xs mt-0.5 truncate" style={{ color: "var(--text-secondary)" }}>{n.body}</div>
                <div className="text-[10px] mt-1" style={{ color: "var(--text-secondary)" }}>
                  {n.created_at ? new Date(n.created_at).toLocaleString("zh-CN") : ""}
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

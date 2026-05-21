import { useState, useEffect, useRef, useCallback } from "react";
import { TodoItem, listTodos, addTodo, markTodoDone } from "../api/sessions";

interface Props {
  sessionId: string | null;
  refreshKey?: number;
}

export default function TodoWidget({ sessionId, refreshKey = 0 }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [todos, setTodos] = useState<TodoItem[]>([]);
  const [newTask, setNewTask] = useState("");
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const pendingCount = todos.filter((t) => !t.done).length;

  const loadTodos = useCallback(async () => {
    if (!sessionId) {
      setTodos([]);
      return;
    }
    try {
      const items = await listTodos(sessionId, "all");
      setTodos(items);
    } catch {
      // ignore
    }
  }, [sessionId]);

  useEffect(() => {
    loadTodos();
  }, [loadTodos, refreshKey]);

  useEffect(() => {
    if (!expanded) return;
    loadTodos();
    if (inputRef.current) inputRef.current.focus();
    const interval = setInterval(loadTodos, 5000);
    return () => clearInterval(interval);
  }, [expanded, loadTodos]);

  const handleToggle = async (id: number) => {
    if (!sessionId) return;
    await markTodoDone(sessionId, id);
    setTodos((prev) => prev.map((t) => (t.id === id ? { ...t, done: true } : t)));
  };

  const handleAdd = async () => {
    const task = newTask.trim();
    if (!task || !sessionId) return;
    try {
      const t = await addTodo(sessionId, task);
      setTodos((prev) => [{ ...t, done: false }, ...prev]);
      setNewTask("");
    } catch {
      // ignore
    }
  };

  if (!expanded) {
    return (
      <button
        onClick={() => setExpanded(true)}
        className="flex flex-col items-center justify-center rounded-full shadow-lg"
        style={{
          position: "fixed",
          bottom: 80,
          right: 16,
          zIndex: 40,
          width: 56,
          height: 56,
          background: "var(--accent)",
          color: "#fff",
          border: "none",
        }}
        title={`${pendingCount} pending tasks`}
      >
        <span style={{ fontSize: 18 }}>📋</span>
        {pendingCount > 0 && (
          <span style={{ fontSize: 10, fontWeight: 700, lineHeight: 1 }}>{pendingCount}</span>
        )}
      </button>
    );
  }

  return (
    <div
      style={{
        position: "fixed",
        bottom: 80,
        right: 16,
        zIndex: 40,
        width: 288,
        maxHeight: 320,
        background: "var(--bg-secondary)",
        border: "1px solid var(--border)",
        borderRadius: 12,
        boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        className="flex items-center justify-between px-3 py-2"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
          📋 Todo {pendingCount > 0 && `(${pendingCount})`}
        </span>
        <button
          onClick={() => setExpanded(false)}
          className="text-xs px-1"
          style={{ color: "var(--text-secondary)" }}
        >
          ✕
        </button>
      </div>

      <div className="overflow-y-auto flex-1" style={{ maxHeight: 200 }}>
        {loading ? (
          <div className="text-xs p-3" style={{ color: "var(--text-secondary)" }}>Loading...</div>
        ) : todos.length === 0 ? (
          <div className="text-xs p-3" style={{ color: "var(--text-secondary)" }}>No tasks</div>
        ) : (
          todos.map((t) => (
            <div
              key={t.id}
              className="flex items-center gap-2 px-3 py-1.5 text-xs"
              style={{ color: t.done ? "var(--text-secondary)" : "var(--text-primary)" }}
            >
              <input
                type="checkbox"
                checked={t.done}
                onChange={() => handleToggle(t.id)}
                className="cursor-pointer"
                style={{ accentColor: "var(--accent)" }}
              />
              <span className={t.done ? "line-through" : ""}>{t.task}</span>
            </div>
          ))
        )}
      </div>

      {sessionId && (
        <div
          className="flex gap-1 p-2"
          style={{ borderTop: "1px solid var(--border)" }}
        >
          <input
            ref={inputRef}
            type="text"
            value={newTask}
            onChange={(e) => setNewTask(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                handleAdd();
              }
            }}
            placeholder="Add task..."
            className="flex-1 px-2 py-1 rounded text-xs outline-none"
            style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
          />
          <button
            onClick={handleAdd}
            disabled={!newTask.trim()}
            className="px-2 py-1 rounded text-xs font-medium text-white disabled:opacity-50"
            style={{ background: "var(--accent)" }}
          >
            +
          </button>
        </div>
      )}
    </div>
  );
}

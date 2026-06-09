import { useTranslation } from "react-i18next";
import { useState, useEffect, useRef, useCallback } from "react";
import { ListTodo, X as XIcon, Plus } from "lucide-react";
import { TodoItem, listTodos, addTodo, markTodoDone } from "../api/sessions";

interface Props {
  sessionId: string | null;
  refreshKey?: number;
}

const DRAG_THRESHOLD = 4;

export default function TodoWidget({ sessionId, refreshKey = 0 }: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [todos, setTodos] = useState<TodoItem[]>([]);
  const [newTask, setNewTask] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Drag state
  const [pos, setPos] = useState({ bottom: 96 }); // ~bottom-24
  const dragRef = useRef<{
    startY: number;
    startBottom: number;
    dragging: boolean;
    moved: boolean;
  } | null>(null);

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
    setTodos((prev) =>
      prev.map((t) => (t.id === id ? { ...t, done: true } : t)),
    );
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

  // --- Drag handlers for the floating button ---
  const onPointerDown = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    const target = e.currentTarget;
    target.setPointerCapture(e.pointerId);
    dragRef.current = {
      startY: e.clientY,
      startBottom: pos.bottom,
      dragging: true,
      moved: false,
    };
  }, [pos]);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d || !d.dragging) return;
    const dy = e.clientY - d.startY;
    if (!d.moved && Math.abs(dy) < DRAG_THRESHOLD) {
      return;
    }
    d.moved = true;
    // dy > 0 means mouse moved down → bottom decreases (button moves up)
    const newBottom = Math.max(16, Math.min(window.innerHeight - 80, d.startBottom - dy));
    setPos({ bottom: newBottom });
  }, []);

  const onPointerUp = useCallback(() => {
    const d = dragRef.current;
    if (!d) return;
    d.dragging = false;
    // Only toggle expanded if we didn't actually drag
    if (!d.moved) {
      setExpanded(true);
    }
    dragRef.current = null;
  }, []);

  if (!expanded) {
    return (
      <button
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        title={`${pendingCount} pending tasks`}
        className="fixed right-3 sm:right-4 z-40 w-12 h-12 sm:w-14 sm:h-14 rounded-full flex flex-col items-center justify-center text-white shadow-[var(--shadow-md)] bg-[var(--accent)] hover:bg-[var(--accent-hover)] transition-colors select-none touch-none"
        style={{ bottom: pos.bottom }}
      >
        <ListTodo size={20} />
        {pendingCount > 0 && (
          <span className="text-[10px] font-bold leading-none mt-0.5">
            {pendingCount}
          </span>
        )}
      </button>
    );
  }

  return (
    <div
      className="fixed right-3 sm:right-4 z-40 w-72 max-h-80 rounded-xl bg-[var(--bg-secondary)] border border-[var(--border)] shadow-[var(--shadow-lg)] flex flex-col animate-scale-in"
      style={{ bottom: pos.bottom }}
    >
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border)]">
        <span className="flex items-center gap-1.5 text-sm font-semibold text-[var(--text-primary)]">
          <ListTodo size={14} className="text-[var(--accent)]" />
          Todo {pendingCount > 0 && `(${pendingCount})`}
        </span>
        <button
          onClick={() => setExpanded(false)}
          className="p-1 rounded text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
        >
          <XIcon size={12} />
        </button>
      </div>

      <div className="overflow-y-auto flex-1 max-h-50">
        {todos.length === 0 ? (
          <div className="text-xs p-3 text-[var(--text-secondary)]">
            {t("todo.empty")}
          </div>
        ) : (
          todos.map((t) => (
            <div
              key={t.id}
              className="flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-[var(--bg-tertiary)]/50 transition-colors"
              style={{
                color: t.done
                  ? "var(--text-secondary)"
                  : "var(--text-primary)",
              }}
            >
              <input
                type="checkbox"
                checked={t.done}
                onChange={() => handleToggle(t.id)}
                className="cursor-pointer accent-[var(--accent)]"
              />
              <span className={t.done ? "line-through" : ""}>{t.task}</span>
            </div>
          ))
        )}
      </div>

      {sessionId && (
        <div className="flex gap-1 p-2 border-t border-[var(--border)]">
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
            placeholder={t("todo.addPlaceholder")}
            className="flex-1 px-2 py-1 rounded text-xs outline-none bg-[var(--bg-tertiary)] text-[var(--text-primary)] border border-[var(--border)] focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/30"
          />
          <button
            onClick={handleAdd}
            disabled={!newTask.trim()}
            className="px-2 py-1 rounded text-xs font-medium text-white disabled:opacity-50 bg-[var(--accent)] hover:bg-[var(--accent-hover)] transition-colors flex items-center justify-center"
          >
            <Plus size={12} />
          </button>
        </div>
      )}
    </div>
  );
}

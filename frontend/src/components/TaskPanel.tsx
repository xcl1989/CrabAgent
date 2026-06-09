import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import {
  Plus,
  X as XIcon,
  Check,
  Trash2,
  Clock,
  ListTodo,
  AlertCircle,
  ExternalLink,
} from "lucide-react";
import {
  Task,
  listTasks,
  createTask,
  updateTask,
  deleteTask,
  type CreateTaskRequest,
} from "../api/tasks";
import { Modal, Button, Input, Textarea, ConfirmDialog } from "./ui";
import { toast } from "./ui/Toast";
import { cn } from "../lib/cn";

interface Props {
  onClose: () => void;
  onSwitchSession?: (sessionId: string) => void;
}

const PRIORITY_COLORS: Record<string, string> = {
  high: "text-red-500",
  medium: "text-yellow-500",
  low: "text-green-500",
};

const PRIORITY_LABELS: Record<string, string> = {
  high: "High", // will use t() inline
  medium: "Medium",
  low: "Low",
};

const STATUS_ORDER = ["pending", "in_progress", "done"];

function isOverdue(task: Task): boolean {
  if (task.status === "done") return false;
  if (!task.deadline) return false;
  return new Date(task.deadline) < new Date();
}

export default function TaskPanel({ onClose, onSwitchSession }: Props) {
  const { t } = useTranslation();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [showCreate, setShowCreate] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newAssignee, setNewAssignee] = useState("");
  const [newDeadline, setNewDeadline] = useState("");
  const [newProject, setNewProject] = useState("");
  const [newPriority, setNewPriority] = useState("medium");
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);

  const loadTasks = async () => {
    try {
      const items = await listTasks(statusFilter);
      setTasks(items);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setLoading(true);
    loadTasks();
  }, [statusFilter]);

  const handleCreate = async () => {
    const title = newTitle.trim();
    if (!title) return;
    try {
      const req: CreateTaskRequest = {
        title,
        description: newDesc.trim(),
        assignee: newAssignee.trim(),
        project: newProject.trim(),
        priority: newPriority,
      };
      if (newDeadline.trim()) {
        req.deadline = newDeadline.trim();
      }
      await createTask(req);
      setNewTitle("");
      setNewDesc("");
      setNewAssignee("");
      setNewDeadline("");
      setNewProject("");
      setNewPriority("medium");
      setShowCreate(false);
      await loadTasks();
    } catch {
      toast.error(t("task.operationFailed"));
    }
  };

  const handleToggleDone = async (task: Task) => {
    try {
      const newStatus = task.status === "done" ? "pending" : "done";
      await updateTask(task.id, { status: newStatus });
      await loadTasks();
    } catch {
      toast.error(t("task.operationFailed"));
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteTask(id);
      setConfirmDelete(null);
      await loadTasks();
    } catch {
      toast.error(t("task.operationFailed"));
    }
  };

  const filters = ["pending", "done", "all"];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="w-full max-w-2xl max-h-[85vh] rounded-xl bg-[var(--bg-primary)] border border-[var(--border)] shadow-[var(--shadow-xl)] flex flex-col animate-scale-in overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)]">
          <div className="flex items-center gap-2">
            <ListTodo size={16} className="text-[var(--accent)]" />
            <span className="text-sm font-semibold text-[var(--text-primary)]">
              {t("task.title")}
            </span>
            <span className="text-xs text-[var(--text-tertiary)]">
              {tasks.length}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <Button
              size="icon"
              variant="ghost"
              onClick={() => setShowCreate(true)}
              title={t("task.newTask")}
            >
              <Plus size={14} />
            </Button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
            >
              <XIcon size={14} />
            </button>
          </div>
        </div>

        {/* Filter tabs */}
        <div className="flex gap-1 px-4 py-2 border-b border-[var(--border)] bg-[var(--bg-secondary)]/50">
          {filters.map((f) => (
            <button
              key={f}
              onClick={() => setStatusFilter(f)}
              className={cn(
                "px-2.5 py-1 rounded-md text-xs font-medium transition-colors",
                statusFilter === f
                  ? "bg-[var(--accent)] text-white"
                  : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
              )}
            >
              {f === "pending" ? t("task.active") : f === "done" ? t("task.done") : t("task.all")}
            </button>
          ))}
        </div>

        {/* Task list */}
        <div className="flex-1 overflow-y-auto p-2">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-sm text-[var(--text-tertiary)]">
              {t("common.loading")}
            </div>
          ) : tasks.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-sm text-[var(--text-tertiary)]">
              <ListTodo size={32} className="mb-2 opacity-40" />
              {statusFilter === "pending"
                ? t("task.noTasks")
                : statusFilter === "done"
                  ? t("task.noTasks")
                  : t("task.noTasks")}
            </div>
          ) : (
            <div className="space-y-1">
              {tasks.map((task) => (
                <div
                  key={task.id}
                  className={cn(
                    "group flex items-start gap-2.5 px-3 py-2.5 rounded-lg transition-colors",
                    task.status === "done"
                      ? "bg-[var(--bg-tertiary)]/30"
                      : "hover:bg-[var(--bg-secondary)]",
                    isOverdue(task) && "bg-red-500/5",
                  )}
                >
                  {/* Checkbox */}
                  <button
                    onClick={() => handleToggleDone(task)}
                    className={cn(
                      "mt-0.5 w-4 h-4 rounded border-2 flex items-center justify-center flex-shrink-0 transition-colors",
                      task.status === "done"
                        ? "bg-[var(--accent)] border-[var(--accent)] text-white"
                        : "border-[var(--border-strong)] hover:border-[var(--accent)]",
                    )}
                  >
                    {task.status === "done" && <Check size={10} />}
                  </button>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      {/* Priority indicator */}
                      <span
                        className={cn(
                          "text-[10px] font-medium",
                          PRIORITY_COLORS[task.priority] || "text-gray-400",
                        )}
                      >
                        ●
                      </span>

                      {/* Title */}
                      <span
                        className={cn(
                          "text-sm",
                          task.status === "done"
                            ? "line-through text-[var(--text-tertiary)]"
                            : "text-[var(--text-primary)] font-medium",
                        )}
                      >
                        {task.title}
                      </span>

                      {/* Project badge */}
                      {task.project && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[var(--bg-tertiary)] text-[var(--text-tertiary)]">
                          {task.project}
                        </span>
                      )}

                      {/* Overdue badge */}
                      {isOverdue(task) && (
                        <span className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-500/10 text-red-500">
                          <AlertCircle size={10} />
                          {t("task.overdue")}
                        </span>
                      )}
                    </div>

                    {/* Description */}
                    {task.description && (
                      <div className="text-xs text-[var(--text-tertiary)] mt-0.5 line-clamp-1">
                        {task.description}
                      </div>
                    )}

                    {/* Meta row */}
                    <div className="flex items-center gap-2 mt-1 flex-wrap">
                      {task.assignee && (
                        <span className="text-[10px] text-[var(--text-tertiary)]">
                          👤 {task.assignee}
                        </span>
                      )}
                      {task.deadline && (
                        <span
                          className={cn(
                            "text-[10px] flex items-center gap-0.5",
                            isOverdue(task)
                              ? "text-red-500"
                              : "text-[var(--text-tertiary)]",
                          )}
                        >
                          <Clock size={10} />
                          {task.deadline.slice(0, 10)}
                        </span>
                      )}
                      <span className="text-[10px] text-[var(--text-tertiary)] capitalize">
                        {PRIORITY_LABELS[task.priority] || task.priority}
                      </span>
                      <span className="text-[10px] text-[var(--text-tertiary)] capitalize">
                        {task.source !== "manual" ? `via ${task.source}` : ""}
                      </span>
                      {task.source_session && onSwitchSession && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onSwitchSession(task.source_session);
                          }}
                          className="text-[10px] flex items-center gap-0.5 text-[var(--brand)] hover:underline ml-auto"
                        >
                          <ExternalLink size={10} />
                          查看详情
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Delete button */}
                  <button
                    onClick={() => setConfirmDelete(task.id)}
                    className="opacity-0 group-hover:opacity-100 p-1 rounded text-[var(--text-tertiary)] hover:text-red-500 hover:bg-red-500/10 transition-all"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Create modal */}
      <Modal
        open={showCreate}
        onOpenChange={setShowCreate}
        title={t("task.newTask")}
      >
        <div className="space-y-3">
          <Input
            placeholder={t("task.titlePlaceholder") + " *"}
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            autoFocus
          />
          <Textarea
            placeholder={t("task.descriptionPlaceholder")}
            value={newDesc}
            onChange={(e) => setNewDesc(e.target.value)}
            rows={2}
          />
          <div className="grid grid-cols-2 gap-2">
            <Input
              placeholder={t("task.assigneePlaceholder")}
              value={newAssignee}
              onChange={(e) => setNewAssignee(e.target.value)}
            />
            <Input
              type="date"
              placeholder={t("task.deadlinePlaceholder")}
              value={newDeadline}
              onChange={(e) => setNewDeadline(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Input
              placeholder={t("task.projectPlaceholder")}
              value={newProject}
              onChange={(e) => setNewProject(e.target.value)}
            />
            <select
              value={newPriority}
              onChange={(e) => setNewPriority(e.target.value)}
              className="px-2 py-1.5 rounded-lg text-xs bg-[var(--bg-tertiary)] text-[var(--text-primary)] border border-[var(--border)] outline-none focus:border-[var(--accent)]"
            >
              <option value="low">{t("task.low")}</option>
              <option value="medium">{t("task.medium")}</option>
              <option value="high">{t("task.high")}</option>
            </select>
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={() => setShowCreate(false)}>
              {t("common.cancel")}
            </Button>
            <Button
              variant="brand"
              onClick={handleCreate}
              disabled={!newTitle.trim()}
            >
              {t("common.create")}
            </Button>
          </div>
        </div>
      </Modal>

      {/* Delete confirm */}
      <ConfirmDialog
        open={confirmDelete !== null}
        onOpenChange={() => setConfirmDelete(null)}
        title={t("task.deleteConfirm")}
        onConfirm={() => { if (confirmDelete !== null) handleDelete(confirmDelete); }}
      />
    </div>
  );
}

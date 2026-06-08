import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { AgentProfile, listAgentProfiles } from "../api/agents";
import { Modal, Button, Textarea, Input } from "./ui";
import { cn } from "../lib/cn";

interface Props {
  onClose: () => void;
  onDelegate: (tasks: { agent_name: string; task: string }[]) => void;
}

export function DelegateModal({ onClose, onDelegate }: Props) {
  const { t } = useTranslation();
  const [agents, setAgents] = useState<AgentProfile[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [task, setTask] = useState("");
  const [customTasks, setCustomTasks] = useState<Record<string, string>>({});

  useEffect(() => {
    listAgentProfiles()
      .then((list) => setAgents(list.filter((a) => a.enabled)))
      .catch(() => {});
  }, []);

  const toggle = (name: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const handleDelegate = () => {
    if (selected.size === 0 || !task.trim()) return;
    const tasks = Array.from(selected).map((name) => ({
      agent_name: name,
      task: customTasks[name]?.trim() || task.trim(),
    }));
    onDelegate(tasks);
  };

  return (
    <Modal
      open={true}
      onOpenChange={(o) => !o && onClose()}
      title={t("delegate.title")}
      description={t("delegate.description")}
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="primary"
            onClick={handleDelegate}
            disabled={selected.size === 0 || !task.trim()}
          >
            {t("delegate.delegateTo", { count: selected.size })}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div>
          <label className="block text-[11px] font-semibold uppercase tracking-wider mb-2 text-[var(--text-secondary)]">
            {t("delegate.selectAgents")}
          </label>
          <div className="flex flex-wrap gap-1.5">
            {agents.map((a) => {
              const isSel = selected.has(a.name);
              return (
                <button
                  key={a.id}
                  onClick={() => toggle(a.name)}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                    isSel
                      ? "bg-[var(--accent-2)] text-white border border-[var(--accent-2)] shadow-[var(--shadow-glow-accent)]"
                      : "bg-[var(--bg-tertiary)] text-[var(--text-secondary)] border border-[var(--border)] hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]",
                  )}
                >
                  <span>{a.icon || "🤖"}</span>
                  <span>{a.display_name}</span>
                </button>
              );
            })}
          </div>
        </div>

        <Textarea
          label={t("delegate.taskDescription")}
          value={task}
          onChange={(e) => setTask(e.target.value)}
          rows={3}
          placeholder={t("delegate.taskPlaceholder")}
          autoFocus
        />

        {selected.size > 1 && (
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-wider mb-2 text-[var(--text-secondary)]">
              {t("delegate.customTasks")}
            </label>
            <p className="text-[11px] text-[var(--text-tertiary)] mb-2">
              {t("delegate.customTasksHint")}
            </p>
            <div className="space-y-2">
              {Array.from(selected).map((name) => {
                const agent = agents.find((a) => a.name === name);
                return (
                  <div key={name} className="flex items-center gap-2">
                    <span className="text-sm shrink-0">{agent?.icon || "🤖"}</span>
                    <span className="text-xs shrink-0 w-20 truncate text-[var(--text-secondary)] font-mono">
                      {name}
                    </span>
                    <Input
                      value={customTasks[name] || ""}
                      onChange={(e) =>
                        setCustomTasks({ ...customTasks, [name]: e.target.value })
                      }
                      placeholder={t("delegate.sameAsAbove")}
                    />
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}

import { useState, useEffect, useCallback } from "react";
import { Sparkles, ChevronDown, FileText, FolderOpen, Loader2 } from "lucide-react";
import { Modal } from "./ui";
import * as settingsApi from "../api/settings";
import type { SkillInfo, SkillDetail } from "../api/settings";
import { cn } from "../lib/cn";

interface Props {
  onClose: () => void;
}

export default function SkillsPanel({ onClose }: Props) {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedName, setExpandedName] = useState<string | null>(null);
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    settingsApi
      .getSkills()
      .then(setSkills)
      .catch(() => setSkills([]))
      .finally(() => setLoading(false));
  }, []);

  const handleToggle = useCallback(
    async (name: string) => {
      if (expandedName === name) {
        setExpandedName(null);
        setDetail(null);
        return;
      }
      setExpandedName(name);
      setDetail(null);
      setDetailLoading(true);
      try {
        const d = await settingsApi.getSkillDetail(name);
        setDetail(d);
      } catch {
        setDetail(null);
      } finally {
        setDetailLoading(false);
      }
    },
    [expandedName],
  );

  return (
    <Modal open={true} onOpenChange={(o) => !o && onClose()} title={
      <span className="flex items-center gap-2">
        <Sparkles size={16} className="text-[var(--brand)]" />
        Skills
      </span>
    } size="lg">
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={20} className="animate-spin text-[var(--text-tertiary)]" />
        </div>
      ) : skills.length === 0 ? (
        <div className="text-center py-8">
          <FileText size={32} className="mx-auto text-[var(--text-tertiary)] mb-3" />
          <p className="text-sm text-[var(--text-secondary)] mb-1">No skills loaded</p>
          <p className="text-xs text-[var(--text-tertiary)]">
            Place <code className="px-1 py-0.5 rounded bg-[var(--bg-tertiary)] text-[10px]">SKILL.md</code> in{" "}
            <code className="px-1 py-0.5 rounded bg-[var(--bg-tertiary)] text-[10px]">~/.crabagent/skills/</code>
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {skills.map((s) => {
            const isOpen = expandedName === s.name;
            return (
              <div
                key={s.name}
                className={cn(
                  "rounded-lg border transition-colors",
                  isOpen
                    ? "border-[var(--brand)]/40 bg-[var(--brand-bg)]/30"
                    : "border-[var(--border)] bg-[var(--bg-tertiary)]/30",
                )}
              >
                {/* Header row — clickable */}
                <button
                  onClick={() => handleToggle(s.name)}
                  className="w-full flex items-start gap-2.5 px-3.5 py-3 text-left"
                >
                  <Sparkles
                    size={14}
                    className={cn(
                      "shrink-0 mt-0.5",
                      isOpen ? "text-[var(--brand)]" : "text-[var(--text-tertiary)]",
                    )}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-[var(--text-primary)]">
                        {s.name}
                      </span>
                      {s.auxiliary_files.length > 0 && (
                        <span className="text-[10px] text-[var(--text-tertiary)] flex items-center gap-0.5">
                          <FileText size={10} />
                          {s.auxiliary_files.length}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-[var(--text-tertiary)] mt-0.5 leading-relaxed line-clamp-2">
                      {s.description}
                    </p>
                  </div>
                  <ChevronDown
                    size={15}
                    className={cn(
                      "shrink-0 mt-0.5 text-[var(--text-tertiary)] transition-transform",
                      isOpen && "rotate-180",
                    )}
                  />
                </button>

                {/* Expanded detail */}
                {isOpen && (
                  <div className="px-3.5 pb-3 border-t border-[var(--border)]/50 pt-2.5 animate-fade-in">
                    {detailLoading ? (
                      <div className="flex items-center gap-2 py-3 text-xs text-[var(--text-tertiary)]">
                        <Loader2 size={12} className="animate-spin" />
                        Loading…
                      </div>
                    ) : detail ? (
                      <>
                        {/* Location */}
                        <div className="flex items-center gap-1.5 mb-2 text-[10px] text-[var(--text-tertiary)]">
                          <FolderOpen size={11} />
                          <span className="font-mono truncate">{detail.location}</span>
                        </div>
                        {/* SKILL.md content */}
                        <pre className="text-xs text-[var(--text-secondary)] bg-[var(--bg-primary)] border border-[var(--border)] rounded-md p-3 max-h-64 overflow-y-auto whitespace-pre-wrap leading-relaxed font-mono">
                          {detail.content}
                        </pre>
                        {/* Auxiliary files */}
                        {detail.auxiliary_files.length > 0 && (
                          <div className="mt-2.5">
                            <div className="text-[10px] font-semibold uppercase tracking-wide text-[var(--text-tertiary)] mb-1.5">
                              Auxiliary Files
                            </div>
                            <div className="space-y-0.5">
                              {detail.auxiliary_files.map((f) => (
                                <div
                                  key={f}
                                  className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)] font-mono"
                                >
                                  <FileText size={11} className="text-[var(--text-tertiary)] shrink-0" />
                                  {f}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </>
                    ) : (
                      <div className="py-2 text-xs text-[var(--danger)]">
                        Failed to load skill detail.
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}

          {/* Footer hint */}
          <p className="text-[10px] text-[var(--text-tertiary)] text-center pt-1">
            AI will automatically load the matching skill when it recognizes a relevant task.
          </p>
        </div>
      )}
    </Modal>
  );
}

import { useState, useCallback, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Clock, Users, CheckCircle2, AlertCircle, Sparkles, Send, FileText, X } from "lucide-react";
import { cn } from "../lib/cn";
import * as sessionsApi from "../api/sessions";

interface MeetingNote {
  id: string;
  timestamp: string;
  speaker: string;
  content: string;
}

interface AISuggestion {
  type: "task" | "question" | "decision";
  content: string;
}

interface Props {
  sessionId: string;
  className?: string;
  onPrompt?: (text: string) => void;
}

export function MeetingPanel({ sessionId, className, onPrompt }: Props) {
  const { t } = useTranslation();
  const [title, setTitle] = useState("");
  const [participants, setParticipants] = useState("");
  const [notes, setNotes] = useState<MeetingNote[]>([]);
  const [inputText, setInputText] = useState("");
  const [inputSpeaker, setInputSpeaker] = useState("");
  const [aiSuggestions, setAiSuggestions] = useState<AISuggestion[]>([]);
  const [status, setStatus] = useState<"active" | "ended">("active");
  const notesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => { notesEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [notes]);

  const addNote = useCallback(() => {
    const text = inputText.trim();
    if (!text) return;
    const now = new Date();
    const ts = `${now.getHours().toString().padStart(2, "0")}:${now.getMinutes().toString().padStart(2, "0")}`;
    const note: MeetingNote = { id: `m-${Date.now()}`, timestamp: ts, speaker: inputSpeaker || "Me", content: text };
    setNotes((prev) => [...prev, note]);
    setInputText("");

    // Auto-analyze every 5 notes
    if ((notes.length + 1) % 5 === 0) {
      analyzeNotes([...notes, note]);
    }
  }, [inputText, inputSpeaker, notes]);

  const analyzeNotes = useCallback(async (allNotes: MeetingNote[]) => {
    const recent = allNotes.slice(-10);
    const text = recent.map((n) => `[${n.timestamp}] ${n.speaker}: ${n.content}`).join("\n");
    const prompt = `以下是会议记录：\n\n${text}\n\n请分析：\n1. 有哪些 action items（需要人去做的事）？格式：{title, assignee, priority}\n2. 有哪些待确认的问题？\n3. 有哪些明确的决策？\n\n只返回 JSON。`;

    try {
      await sessionsApi.sendPrompt(sessionId, prompt);
    } catch {}
  }, [sessionId]);

  const handleEnd = useCallback(() => {
    setStatus("ended");
    const summary = notes.map((n) => `[${n.timestamp}] ${n.speaker}: ${n.content}`).join("\n");
    const prompt = `会议结束。请根据以下记录生成会议纪要，包含摘要、行动项、待确认问题和决策。\n\n${summary}`;
    onPrompt?.(prompt);
  }, [notes, onPrompt]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); addNote(); }
  };

  return (
    <div className={cn("flex flex-col h-full bg-[var(--bg-primary)]", className)}>
      {/* Header */}
      <div className="px-3 py-2 border-b border-[var(--border)] bg-[var(--bg-secondary)] shrink-0">
        <div className="flex items-center gap-2 mb-1">
          <span className={cn("w-2 h-2 rounded-full", status === "active" ? "bg-[var(--success)] animate-pulse" : "bg-[var(--text-tertiary)]")} />
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={t("meeting.titlePlaceholder")}
            className="flex-1 bg-transparent text-sm font-medium text-[var(--text-primary)] border-0 outline-none placeholder:text-[var(--text-tertiary)]"
          />
          {status === "active" && (
            <button onClick={handleEnd} className="flex items-center gap-1 px-2 py-1 rounded text-[10px] bg-[var(--danger-bg)] text-[var(--danger)] hover:bg-[var(--danger-border)] transition-colors">
              <X size={12} /> {t("meeting.end")}
            </button>
          )}
        </div>
        <div className="flex items-center gap-2 text-[11px] text-[var(--text-tertiary)]">
          <Clock size={12} /> <span>{new Date().toLocaleString()}</span>
          <Users size={12} className="ml-2" />
          <input
            value={participants}
            onChange={(e) => setParticipants(e.target.value)}
            placeholder={t("meeting.participantsPlaceholder")}
            className="flex-1 bg-transparent border-0 outline-none text-[var(--text-tertiary)] placeholder:text-[var(--text-tertiary)]/50"
          />
        </div>
      </div>

      {/* Notes area */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
        {notes.map((note) => (
          <div key={note.id} className="flex gap-2 text-[13px]">
            <span className="text-[10px] text-[var(--text-tertiary)] font-mono shrink-0 pt-0.5">{note.timestamp}</span>
            <span className="font-medium shrink-0 text-[var(--text-secondary)]">{note.speaker}</span>
            <span className="text-[var(--text-primary)]">{note.content}</span>
          </div>
        ))}
        <div ref={notesEndRef} />

        {/* AI suggestions */}
        {aiSuggestions.length > 0 && (
          <div className="mt-3 p-2 rounded bg-[var(--accent-bg)] border border-[var(--accent-border)]">
            <div className="flex items-center gap-1 text-[11px] font-medium text-[var(--accent)] mb-1">
              <Sparkles size={12} /> AI Analysis
            </div>
            {aiSuggestions.map((s, i) => (
              <div key={i} className="text-[11px] text-[var(--text-secondary)] flex items-start gap-1.5 py-0.5">
                {s.type === "task" && <CheckCircle2 size={11} className="mt-0.5 shrink-0 text-[var(--success)]" />}
                {s.type === "question" && <AlertCircle size={11} className="mt-0.5 shrink-0 text-[var(--warning)]" />}
                {s.type === "decision" && <FileText size={11} className="mt-0.5 shrink-0 text-[var(--accent)]" />}
                {s.content}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Input area */}
      {status === "active" && (
        <div className="px-3 py-2 border-t border-[var(--border)] bg-[var(--bg-secondary)] shrink-0">
          <div className="flex gap-1 mb-1">
            <input
              value={inputSpeaker}
              onChange={(e) => setInputSpeaker(e.target.value)}
              placeholder={t("meeting.speakerPlaceholder")}
              className="w-16 bg-transparent text-[11px] text-[var(--text-tertiary)] border-0 outline-none placeholder:text-[var(--text-tertiary)]/50"
            />
          </div>
          <div className="flex gap-2">
            <textarea
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={t("meeting.notePlaceholder")}
              rows={2}
              className="flex-1 bg-[var(--bg-tertiary)] text-[12px] text-[var(--text-primary)] px-2 py-1.5 rounded border border-[var(--border)] resize-none outline-none placeholder:text-[var(--text-tertiary)]/50"
            />
            <button onClick={addNote} className="self-end p-1.5 rounded bg-[var(--brand)] text-white hover:bg-[var(--brand-hover)] transition-colors">
              <Send size={14} />
            </button>
          </div>
        </div>
      )}

      {/* End summary */}
      {status === "ended" && (
        <div className="px-3 py-3 border-t border-[var(--border)] text-center text-[11px] text-[var(--text-tertiary)]">
          {t("meeting.ended")}
        </div>
      )}
    </div>
  );
}

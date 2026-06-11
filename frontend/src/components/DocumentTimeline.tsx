import { CheckCircle2, Loader2, XCircle, FileText } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "../lib/cn";

export interface DocOpEvent {
  message: string;
  timestamp: number;
  status: "running" | "done" | "error";
}

interface Props {
  events: DocOpEvent[];
  className?: string;
}

export function DocumentTimeline({ events, className }: Props) {
  const { t } = useTranslation();

  if (events.length === 0) {
    return (
      <div className={cn("flex flex-col items-center justify-center h-full text-[var(--text-tertiary)] text-xs gap-2", className)}>
        <FileText size={24} opacity={0.3} />
        <span>{t("document.noDocument")}</span>
      </div>
    );
  }

  return (
    <div className={cn("space-y-1 p-3", className)}>
      {events.map((ev, i) => (
        <div
          key={`${ev.timestamp}-${i}`}
          className={cn(
            "flex items-start gap-2 px-2 py-1.5 rounded-md text-xs transition-colors",
            ev.status === "running" && "bg-[var(--accent-bg)]",
            ev.status === "done" && "text-[var(--text-secondary)]",
            ev.status === "error" && "bg-[var(--danger-bg)] text-[var(--danger)]",
          )}
        >
          {/* status icon */}
          <span className="mt-0.5 shrink-0">
            {ev.status === "running" ? (
              <Loader2 size={12} className="animate-spin text-[var(--accent)]" />
            ) : ev.status === "done" ? (
              <CheckCircle2 size={12} className="text-[var(--success)]" />
            ) : (
              <XCircle size={12} className="text-[var(--danger)]" />
            )}
          </span>

          {/* message text */}
          <span className="leading-relaxed break-words min-w-0">
            {ev.message}
          </span>

          {/* timestamp */}
          <span className="ml-auto shrink-0 text-[var(--text-tertiary)] tabular-nums">
            {_formatTime(ev.timestamp)}
          </span>
        </div>
      ))}
    </div>
  );
}

function _formatTime(ts: number): string {
  const d = new Date(ts);
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${mm}:${ss}`;
}

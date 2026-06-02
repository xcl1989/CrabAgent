import { type ReactNode } from "react";
import { Inbox, Loader2, AlertCircle } from "lucide-react";
import { cn } from "../../lib/cn";

interface StateProps {
  icon?: ReactNode;
  title?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  /** Compact mode for inline panels (smaller padding) */
  compact?: boolean;
  className?: string;
}

export function EmptyState({
  icon = <Inbox size={32} />,
  title = "Nothing here yet",
  description,
  action,
  compact = false,
  className,
}: StateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center mx-auto",
        compact ? "py-6 px-3 gap-2" : "py-12 px-4 gap-3",
        className,
      )}
    >
      <div className="text-[var(--text-tertiary)]">{icon}</div>
      {title && (
        <div className="text-sm font-medium text-[var(--text-secondary)]">
          {title}
        </div>
      )}
      {description && (
        <div className="text-xs text-[var(--text-tertiary)] max-w-xs leading-relaxed">
          {description}
        </div>
      )}
      {action}
    </div>
  );
}

export function LoadingState({
  title = "Loading…",
  compact = false,
  className,
}: {
  title?: ReactNode;
  compact?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center gap-2 mx-auto",
        compact ? "py-6" : "py-12",
        className,
      )}
    >
      <Loader2 size={20} className="animate-spin text-[var(--brand)]" />
      <div className="text-xs text-[var(--text-tertiary)]">{title}</div>
    </div>
  );
}

export function ErrorState({
  title = "Something went wrong",
  description,
  action,
  compact = false,
  className,
}: {
  title?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center gap-2 mx-auto",
        compact ? "py-6 px-3" : "py-12 px-4",
        className,
      )}
    >
      <AlertCircle size={28} className="text-[var(--danger)]" />
      <div className="text-sm font-medium text-[var(--text-primary)]">
        {title}
      </div>
      {description && (
        <div className="text-xs text-[var(--text-tertiary)] max-w-xs leading-relaxed">
          {description}
        </div>
      )}
      {action}
    </div>
  );
}

export function Skeleton({
  className,
  ...rest
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-md",
        "bg-[linear-gradient(90deg,var(--bg-tertiary)_0%,var(--bg-elevated)_50%,var(--bg-tertiary)_100%)]",
        "bg-[length:200%_100%] animate-[shimmer_1.6s_ease-in-out_infinite]",
        className,
      )}
      {...rest}
    />
  );
}

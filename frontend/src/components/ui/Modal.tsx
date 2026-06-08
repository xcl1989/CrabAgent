import { useTranslation } from "react-i18next";
import {
  Close as DialogClose,
  Content as DialogContent,
  Description as DialogDescription,
  Overlay as DialogOverlay,
  Portal as DialogPortal,
  Root as DialogRoot,
  Title as DialogTitle,
  Trigger as DialogTrigger,
} from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { type ReactNode, type HTMLAttributes } from "react";
import { cn } from "../../lib/cn";

export type ModalSize = "sm" | "md" | "lg" | "xl" | "full";

const sizeClass: Record<ModalSize, string> = {
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-lg",
  xl: "max-w-2xl",
  full: "max-w-[min(95vw,1200px)]",
};

interface ModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: ReactNode;
  description?: ReactNode;
  size?: ModalSize;
  /** Hide the default X button */
  hideClose?: boolean;
  /** Render a custom footer (replaces default empty padding) */
  footer?: ReactNode;
  /** Disable backdrop click closing (defaults to false = allow) */
  disableBackdropClose?: boolean;
  children: ReactNode;
}

export function Modal({
  open,
  onOpenChange,
  title,
  description,
  size = "md",
  hideClose = false,
  footer,
  disableBackdropClose = false,
  children,
}: ModalProps) {
  const { t } = useTranslation();
  return (
    <DialogRoot
      open={open}
      onOpenChange={(o) => {
        if (!o && disableBackdropClose) return;
        onOpenChange(o);
      }}
    >
      <DialogPortal>
        <DialogOverlay
          className="fixed inset-0 z-50 bg-[var(--bg-overlay)] backdrop-blur-sm data-[state=open]:animate-fade-in"
        />
        <DialogContent
          className={cn(
            "fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2",
            "w-[calc(100%-2rem)] outline-none",
            "bg-[var(--bg-secondary)] text-[var(--text-primary)]",
            "rounded-2xl border border-[var(--border)]",
            "shadow-[var(--shadow-lg)]",
            "flex flex-col max-h-[90vh]",
            "data-[state=open]:animate-scale-in",
            sizeClass[size],
          )}
        >
          {(title || !hideClose) && (
            <header className="flex items-start justify-between gap-4 px-5 pt-4 pb-3 border-b border-[var(--border-subtle)]">
              <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                {title && (
                  <DialogTitle
                    className={cn(
                      "text-base font-semibold text-[var(--text-primary)]",
                      "truncate",
                    )}
                  >
                    {title}
                  </DialogTitle>
                )}
                {description && (
                  <DialogDescription className="text-xs text-[var(--text-secondary)]">
                    {description}
                  </DialogDescription>
                )}
              </div>
              {!hideClose && (
                <DialogClose
                  className={cn(
                    "shrink-0 p-1.5 rounded-lg",
                    "text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
                    "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]",
                  )}
                  aria-label={t("modal.close")}
                >
                  <X size={16} />
                </DialogClose>
              )}
            </header>
          )}
          <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && (
            <footer className="px-5 py-3 border-t border-[var(--border-subtle)] flex items-center justify-end gap-2">
              {footer}
            </footer>
          )}
        </DialogContent>
      </DialogPortal>
    </DialogRoot>
  );
}

/** Lightweight unstyled modal trigger if needed */
export const ModalTrigger = DialogTrigger;

/** Container for action buttons inside modal footer */
export function ModalActions({
  children,
  className,
  ...rest
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("flex items-center gap-2", className)} {...rest}>
      {children}
    </div>
  );
}

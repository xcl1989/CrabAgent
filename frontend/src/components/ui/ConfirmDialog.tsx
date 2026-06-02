import { useState, type ReactNode } from "react";
import { AlertTriangle, HelpCircle, Info, CheckCircle } from "lucide-react";
import { Modal } from "./Modal";
import { Button } from "./Button";

export type ConfirmTone = "danger" | "warning" | "info" | "success";

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  confirmText?: string;
  cancelText?: string;
  tone?: ConfirmTone;
  /** Override the icon */
  icon?: ReactNode;
  onConfirm: () => void | Promise<void>;
}

const toneIcon: Record<ConfirmTone, ReactNode> = {
  danger: <AlertTriangle size={20} className="text-[var(--danger)]" />,
  warning: <HelpCircle size={20} className="text-[var(--warning)]" />,
  info: <Info size={20} className="text-[var(--accent)]" />,
  success: <CheckCircle size={20} className="text-[var(--success)]" />,
};

const toneButton: Record<ConfirmTone, "primary" | "danger"> = {
  danger: "danger",
  warning: "primary",
  info: "primary",
  success: "primary",
};

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmText = "Confirm",
  cancelText = "Cancel",
  tone = "info",
  icon,
  onConfirm,
}: ConfirmDialogProps) {
  const [busy, setBusy] = useState(false);

  const handleConfirm = async () => {
    setBusy(true);
    try {
      await onConfirm();
      onOpenChange(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onOpenChange={(o) => !busy && onOpenChange(o)}
      size="sm"
      title={
        <div className="flex items-center gap-2.5">
          {icon ?? toneIcon[tone]}
          <span>{title}</span>
        </div>
      }
      footer={
        <>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onOpenChange(false)}
            disabled={busy}
          >
            {cancelText}
          </Button>
          <Button
            variant={toneButton[tone]}
            size="sm"
            loading={busy}
            onClick={handleConfirm}
          >
            {confirmText}
          </Button>
        </>
      }
    >
      {description && (
        <div className="text-sm text-[var(--text-secondary)] leading-relaxed">
          {description}
        </div>
      )}
    </Modal>
  );
}

/**
 * Promise-based confirm helper for ergonomic imperative usage.
 * Usage:
 *   if (await confirm({ title: "Delete?", tone: "danger" })) { ... }
 */
interface ConfirmOptions {
  title: ReactNode;
  description?: ReactNode;
  confirmText?: string;
  cancelText?: string;
  tone?: ConfirmTone;
}
export function confirmDialog(): {
  ConfirmHost: () => ReactNode;
  confirm: (opts: ConfirmOptions) => Promise<boolean>;
} {
  let openSetter: (o: boolean) => void = () => {};
  let resolveRef: ((v: boolean) => void) | null = null;
  let optsRef: { current: ConfirmOptions } = { current: { title: "" } };

  const confirm = (opts: ConfirmOptions) =>
    new Promise<boolean>((resolve) => {
      optsRef.current = opts;
      resolveRef = resolve;
      openSetter(true);
    });

  const ConfirmHost = () => {
    const [open, setOpen] = useState(false);
    openSetter = setOpen;
    return (
      <ConfirmDialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o && resolveRef) {
            resolveRef(false);
            resolveRef = null;
          }
        }}
        title={optsRef.current.title}
        description={optsRef.current.description}
        confirmText={optsRef.current.confirmText}
        cancelText={optsRef.current.cancelText}
        tone={optsRef.current.tone}
        onConfirm={() => {
          if (resolveRef) {
            resolveRef(true);
            resolveRef = null;
          }
        }}
      />
    );
  };

  return { ConfirmHost, confirm };
}

import { Toaster as SonnerToaster, toast as sonnerToast } from "sonner";
import { CheckCircle2, AlertCircle, Info, AlertTriangle } from "lucide-react";
import { useTheme } from "../../lib/theme";

export function Toaster() {
  const { theme } = useTheme();
  return (
    <SonnerToaster
      theme={theme}
      position="bottom-right"
      richColors={false}
      closeButton
      duration={4000}
      toastOptions={{
        unstyled: false,
        style: {
          background: "var(--bg-secondary)",
          color: "var(--text-primary)",
          border: "1px solid var(--border)",
          borderRadius: "12px",
          boxShadow: "var(--shadow-lg)",
          fontSize: "13px",
        },
        className: "crabagent-toast",
      }}
    />
  );
}

interface ToastHelpers {
  success: (msg: string, opts?: { description?: string }) => void;
  error: (msg: string, opts?: { description?: string }) => void;
  warning: (msg: string, opts?: { description?: string }) => void;
  info: (msg: string, opts?: { description?: string }) => void;
  loading: (msg: string) => string | number;
  dismiss: (id?: string | number) => void;
}

export const toast: ToastHelpers = {
  success: (msg, opts) =>
    sonnerToast.success(msg, {
      description: opts?.description,
      icon: <CheckCircle2 size={16} className="text-[var(--success)]" />,
    }),
  error: (msg, opts) =>
    sonnerToast.error(msg, {
      description: opts?.description,
      icon: <AlertCircle size={16} className="text-[var(--danger)]" />,
    }),
  warning: (msg, opts) =>
    sonnerToast.warning(msg, {
      description: opts?.description,
      icon: <AlertTriangle size={16} className="text-[var(--warning)]" />,
    }),
  info: (msg, opts) =>
    sonnerToast.info(msg, {
      description: opts?.description,
      icon: <Info size={16} className="text-[var(--accent)]" />,
    }),
  loading: (msg) => sonnerToast.loading(msg),
  dismiss: (id) => sonnerToast.dismiss(id),
};

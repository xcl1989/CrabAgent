import { useTranslation } from "react-i18next";
import { Loader2, AlertTriangle, FileText } from "lucide-react";
import { cn } from "../lib/cn";

interface Props {
  html: string | null;
  loading?: boolean;
  error?: string;
  className?: string;
}

export function DocumentPreview({ html, loading, error, className }: Props) {
  const { t } = useTranslation();

  if (loading) {
    return (
      <div className={cn("flex flex-col items-center justify-center h-full gap-3", className)}>
        <Loader2 size={24} className="animate-spin text-[var(--text-tertiary)]" />
        <span className="text-xs text-[var(--text-tertiary)]">{t("document.loadingPreview")}</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className={cn("flex flex-col items-center justify-center h-full gap-3 p-6", className)}>
        <AlertTriangle size={24} className="text-[var(--danger)]" />
        <span className="text-xs text-[var(--danger)] text-center">{error}</span>
      </div>
    );
  }

  if (!html) {
    return (
      <div className={cn("flex flex-col items-center justify-center h-full gap-3", className)}>
        <FileText size={28} className="text-[var(--text-tertiary)]" opacity={0.4} />
        <span className="text-xs text-[var(--text-tertiary)]">{t("document.previewFailed")}</span>
      </div>
    );
  }

  return (
    <div className={cn("h-full", className)}>
      <iframe
        srcDoc={html}
        title="Document Preview"
        className="w-full h-full border-0"
        sandbox="allow-scripts allow-same-origin"
        style={{ background: "#fff" }}
      />
    </div>
  );
}

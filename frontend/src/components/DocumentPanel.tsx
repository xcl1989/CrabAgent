import { useState, useCallback, useEffect } from "react";
import { X, Download, RefreshCw, Eye, Clock, FileText, Maximize2, Minimize2, FileSpreadsheet, Presentation } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "../lib/cn";
import { DocumentTimeline, DocOpEvent } from "./DocumentTimeline";
import { DocumentPreview } from "./DocumentPreview";
import * as documentsApi from "../api/documents";

type Tab = "preview" | "timeline";

export interface DocState {
  /** Display name (e.g. "report.pptx") */
  fileName: string;
  /** Full path for display */
  filePath: string;
  /** Whether the AI is currently operating on this doc */
  busy: boolean;
  /** Latest HTML preview content */
  previewHtml: string | null;
  /** Preview loading state */
  previewLoading: boolean;
  /** Preview error message */
  previewError: string | null;
  /** Operation events for timeline */
  events: DocOpEvent[];
  /** Workspace for file operations */
  workspace?: string;
}

interface Props {
  doc: DocState | null;
  onClose: () => void;
  onDownload?: () => void;
  onRefreshPreview?: () => void;
  /** Whether the panel is in maximized (full-width) mode */
  maximized?: boolean;
  /** Toggle maximize / restore */
  onToggleMaximize?: () => void;
  className?: string;
}

export function DocumentPanel({
  doc,
  onClose,
  onDownload,
  onRefreshPreview,
  maximized,
  onToggleMaximize,
  className,
}: Props) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("preview");
  const [editing, setEditing] = useState(false);
  // Local preview override from quick-edit, cleared on next refresh
  const [localPreviewHtml, setLocalPreviewHtml] = useState<string | null>(null);

  const handleQuickEdit = useCallback(async (oldText: string, newText: string) => {
    if (!doc?.filePath) return;
    setEditing(true);
    try {
      const result = await documentsApi.quickEditText({
        path: doc.filePath,
        old_text: oldText,
        new_text: newText,
        workspace: doc.workspace || "",
      });
      if (result.preview_html) {
        setLocalPreviewHtml(result.preview_html);
      }
      if (result.status === "no_match") {
        console.warn("Quick edit: text not found:", oldText);
      }
      // Also trigger server refresh so next page load has latest
      onRefreshPreview?.();
    } catch (e: any) {
      console.error("Quick edit failed:", e);
      onRefreshPreview?.();
    } finally {
      setEditing(false);
    }
  }, [doc?.filePath, doc?.workspace, onRefreshPreview]);

  // Clear local preview when doc changes
  useEffect(() => {
    setLocalPreviewHtml(null);
  }, [doc?.previewHtml]);

  const handleDownload = useCallback(() => {
    onDownload?.();
  }, [onDownload]);

  if (!doc) {
    return (
      <div className={cn("flex flex-col h-full", className)}>
        <Header fileName="" onClose={onClose} maximized={maximized} onToggleMaximize={onToggleMaximize} />
        <div className="flex-1 flex items-center justify-center text-[var(--text-tertiary)] text-xs gap-2">
          <FileText size={24} opacity={0.3} />
          <span>{t("document.noDocument")}</span>
        </div>
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col h-full", className)}>
      {/* Header */}
      <Header fileName={doc.fileName} onClose={onClose} maximized={maximized} onToggleMaximize={onToggleMaximize} />

      {/* Status bar */}
      {doc.busy && (
        <div className="px-3 py-1.5 text-xs text-[var(--accent)] bg-[var(--accent-bg)] flex items-center gap-1.5 border-b border-[var(--border)]">
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)] animate-pulse" />
          AI is editing...
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 px-2 pt-2 border-b border-[var(--border)]">
        {(["preview", "timeline"] as Tab[]).map((tabId) => (
          <button
            key={tabId}
            onClick={() => setTab(tabId)}
            className={cn(
              "flex items-center gap-1 px-2.5 py-1.5 rounded-t-md text-xs font-medium transition-all",
              tab === tabId
                ? "bg-[var(--bg-secondary)] text-[var(--text-primary)] border border-[var(--border)] border-b-transparent -mb-px"
                : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]",
            )}
          >
            {tabId === "preview" ? <Eye size={12} /> : <Clock size={12} />}
            {tabId === "preview" ? t("document.tabPreview") : t("document.tabTimeline")}
            {tabId === "timeline" && doc.events.length > 0 && (
              <span className="ml-1 w-4 h-4 flex items-center justify-center rounded-full bg-[var(--accent-bg)] text-[10px] text-[var(--accent)]">
                {doc.events.length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Status bar during edit */}
      {editing && (
        <div className="px-3 py-1 text-xs text-[var(--success)] bg-[var(--success-bg)] flex items-center gap-1.5 border-b border-[var(--border)]">
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--success)] animate-pulse" />
          Applying edit...
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {tab === "preview" ? (
          <DocumentPreview
            html={localPreviewHtml ?? doc.previewHtml}
            loading={doc.previewLoading}
            error={doc.previewError || undefined}
            className="h-full"
            onQuickEdit={handleQuickEdit}
          />
        ) : (
          <DocumentTimeline events={doc.events} className="h-full overflow-y-auto" />
        )}
      </div>

      {/* Bottom actions */}
      <div className="flex items-center gap-1 px-2 py-1.5 border-t border-[var(--border)] bg-[var(--bg-tertiary)]">
        <button
          onClick={handleDownload}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)] transition-colors"
          title={t("document.download")}
        >
          <Download size={12} />
          {t("document.download")}
        </button>
        <button
          onClick={() => {
            setLocalPreviewHtml(null);
            onRefreshPreview?.();
          }}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)] transition-colors"
          title={t("document.refresh")}
        >
          <RefreshCw size={12} />
          {t("document.refresh")}
        </button>
      </div>
    </div>
  );
}

function Header({ fileName, onClose, maximized, onToggleMaximize }: {
  fileName: string;
  onClose: () => void;
  maximized?: boolean;
  onToggleMaximize?: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border)]">
      <div className="flex items-center gap-2 min-w-0">
        <FileIcon fileName={fileName} />
        <span className="text-sm font-medium truncate">
          {fileName || t("document.title")}
        </span>
      </div>
      <div className="flex items-center gap-0.5 shrink-0">
        {onToggleMaximize && (
          <button
            onClick={onToggleMaximize}
            className="p-1 rounded hover:bg-[var(--bg-tertiary)] text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
            title={maximized ? t("document.restore") : t("document.maximize")}
          >
            {maximized ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
        )}
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-[var(--bg-tertiary)] text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  );
}

function FileIcon({ fileName }: { fileName: string }) {
  const ext = fileName?.toLowerCase().split(".").pop() || "";
  if (ext === "xlsx") return <FileSpreadsheet size={16} style={{ color: "#217346" }} />;
  if (ext === "pptx") return <Presentation size={16} style={{ color: "#d04525" }} />;
  if (ext === "docx") return <FileText size={16} style={{ color: "#2b579a" }} />;
  return <FileText size={16} style={{ color: "var(--text-tertiary)" }} />;
}



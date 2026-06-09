import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Check, Copy, ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "../../lib/cn";

interface CodeBlockProps {
  language?: string;
  code: string;
  /** Max lines visible before collapsing; default 20 */
  collapseAfter?: number;
  /** Disable the copy button */
  hideCopy?: boolean;
  className?: string;
  /** Render children instead of plain code (used when react-markdown already tokenizes via rehype-highlight) */
  children?: ReactNode;
}

export function CodeBlock({
  language,
  code,
  collapseAfter = 20,
  hideCopy = false,
  className,
  children,
}: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const { t } = useTranslation();

  const lines = code.split("\n");
  const shouldCollapse = lines.length > collapseAfter + 2;
  const visibleCode = shouldCollapse && !expanded
    ? lines.slice(0, collapseAfter).join("\n")
    : code;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // ignore
    }
  };

  return (
    <div
      className={cn(
        "group relative my-3 rounded-xl overflow-hidden",
        "bg-[var(--code-bg)] border border-[var(--code-border)]",
        className,
      )}
    >
      {(language || !hideCopy) && (
        <div className="flex items-center justify-between px-3 py-1.5 border-b border-[var(--code-border)] bg-[var(--bg-secondary)]">
          <span className="text-[10px] uppercase tracking-wider text-[var(--text-tertiary)] font-mono">
            {language || "text"}
          </span>
          {!hideCopy && (
            <button
              onClick={handleCopy}
              className={cn(
                "flex items-center gap-1 px-1.5 py-0.5 rounded",
                "text-[10px] text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
                "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]",
              )}
              aria-label={t("codeBlock.copy")}
            >
              {copied ? (
                <>
                  <Check size={11} className="text-[var(--success)]" />
                  <span className="text-[var(--success)]">{t("codeBlock.copied")}</span>
                </>
              ) : (
                <>
                  <Copy size={11} />
                  <span>{t("codeBlock.copy")}</span>
                </>
              )}
            </button>
          )}
        </div>
      )}
      <pre className="m-0 bg-transparent! border-0! p-0!">
        <code
          className={cn(
            "block px-4 py-3 text-[13px] leading-[1.6] overflow-x-auto",
            "bg-transparent! border-0!",
          )}
        >
          {children ?? visibleCode}
        </code>
      </pre>
      {shouldCollapse && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className={cn(
            "w-full flex items-center justify-center gap-1 py-1.5",
            "border-t border-[var(--code-border)]",
            "text-[11px] text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)]",
            "transition-colors",
          )}
        >
          {expanded ? (
            <>
              <ChevronUp size={12} /> Collapse
            </>
          ) : (
            <>
              <ChevronDown size={12} /> Show {lines.length - collapseAfter} more lines
            </>
          )}
        </button>
      )}
    </div>
  );
}

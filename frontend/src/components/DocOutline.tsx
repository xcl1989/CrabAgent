import { useTranslation } from "react-i18next";
import { List } from "lucide-react";
import { cn } from "../lib/cn";

export interface OutlineItem {
  level: number;
  text: string;
  index: number;
}

interface Props {
  items: OutlineItem[];
  activeIndex?: number;
  onSelect: (index: number) => void;
  className?: string;
}

export function DocOutline({ items, activeIndex, onSelect, className }: Props) {
  const { t } = useTranslation();

  if (items.length === 0) {
    return (
      <div className={cn("w-[200px] shrink-0 border-r border-[var(--border)] flex flex-col bg-[var(--bg-secondary)]", className)}>
        <div className="px-3 py-2 text-xs font-semibold text-[var(--text-tertiary)] flex items-center gap-1.5 border-b border-[var(--border)]">
          <List size={12} />
          {t("document.outline")}
        </div>
        <div className="flex-1 flex items-center justify-center text-[11px] text-[var(--text-tertiary)] px-3 text-center">
          {t("document.outlineEmpty")}
        </div>
      </div>
    );
  }

  return (
    <div className={cn("w-[200px] shrink-0 border-r border-[var(--border)] flex flex-col bg-[var(--bg-secondary)] overflow-hidden", className)}>
      <div className="px-3 py-2 text-xs font-semibold text-[var(--text-tertiary)] flex items-center gap-1.5 border-b border-[var(--border)] shrink-0">
        <List size={12} />
        {t("document.outline")}
      </div>
      <div className="flex-1 overflow-y-auto py-1">
        {items.map((item) => (
          <button
            key={item.index}
            onClick={() => onSelect(item.index)}
            className={cn(
              "w-full text-left px-3 py-1 text-[11px] leading-relaxed transition-colors truncate",
              "hover:bg-[var(--bg-tertiary)]",
              activeIndex === item.index
                ? "text-[var(--brand)] bg-[var(--brand-bg)] border-l-2 border-[var(--brand)]"
                : "text-[var(--text-secondary)]",
            )}
            style={{ paddingLeft: `${12 + (item.level - 1) * 12}px` }}
            title={item.text}
          >
            {item.text}
          </button>
        ))}
      </div>
    </div>
  );
}

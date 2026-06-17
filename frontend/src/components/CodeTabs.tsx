import { X, File } from "lucide-react";
import { cn } from "../lib/cn";

interface CodeTab {
  path: string;
  name: string;
  modified?: boolean;
}

interface Props {
  tabs: CodeTab[];
  activePath: string | null;
  onSelect: (path: string) => void;
  onClose: (path: string) => void;
}

export function CodeTabs({ tabs, activePath, onSelect, onClose }: Props) {
  return (
    <div className="flex items-center overflow-x-auto border-b border-[var(--border)] bg-[var(--bg-secondary)] shrink-0">
      {tabs.map((tab) => (
        <div
          key={tab.path}
          onClick={() => onSelect(tab.path)}
          className={cn(
            "flex items-center gap-1.5 px-3 py-1.5 text-[11px] border-r border-[var(--border)] cursor-pointer shrink-0 transition-colors",
            tab.path === activePath
              ? "bg-[var(--bg-primary)] text-[var(--text-primary)] border-b-2 border-b-[var(--brand)]"
              : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]",
          )}
        >
          <File size={12} />
          <span className="truncate max-w-[120px]">{tab.name}</span>
          {tab.modified && <span className="w-1.5 h-1.5 rounded-full bg-[var(--warning)]" />}
          <button
            onClick={(e) => { e.stopPropagation(); onClose(tab.path); }}
            className="p-0.5 rounded hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)] transition-colors"
          >
            <X size={10} />
          </button>
        </div>
      ))}
    </div>
  );
}

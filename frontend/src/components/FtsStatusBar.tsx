import { Loader2, Search } from "lucide-react";
import { useEffect, useState } from "react";

interface Props {
  done: number;
  total: number;
}

/** Non-blocking floating pill showing FTS indexing progress.
 *  Sits at bottom-right, fades out when complete. */
export function FtsStatusBar({ done, total }: Props) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    if (done >= total) {
      const t = setTimeout(() => setVisible(false), 1500);
      return () => clearTimeout(t);
    }
  }, [done, total]);

  if (!visible) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[9998] animate-slide-up pointer-events-none">
      <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-[var(--bg-secondary)] border border-[var(--border)] shadow-lg">
        <Search size={13} className="text-[var(--accent-2)] shrink-0" />
        <span className="text-[11px] text-[var(--text-secondary)] whitespace-nowrap">
          索引消息 {done.toLocaleString()} / {total.toLocaleString()}
        </span>
        <div className="w-20 h-1 rounded-full bg-[var(--bg-tertiary)] overflow-hidden">
          <div
            className="h-full rounded-full bg-[var(--accent-2)] transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="text-[10px] text-[var(--text-tertiary)] font-mono w-8 text-right">
          {pct}%
        </span>
        <Loader2 size={11} className="animate-spin text-[var(--text-tertiary)] shrink-0" />
      </div>
    </div>
  );
}

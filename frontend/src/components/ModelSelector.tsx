import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { ChevronDown, Check, Search } from "lucide-react";
import { cn } from "../lib/cn";
import { ProviderModels } from "../hooks/useModelSelector";

interface Props {
  providerModels: ProviderModels[];
  selectedModel: string;
  onChange: (modelId: string, providerName: string) => void;
  disabled?: boolean;
  className?: string;
}

export default function ModelSelector({
  providerModels,
  selectedModel,
  onChange,
  disabled,
  className,
}: Props) {
  const selectedProviderRef = useRef<string | null>(null);
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState<string>(
    selectedProviderRef.current ? `${selectedProviderRef.current}/${selectedModel}` : selectedModel
  );
  const [searchQuery, setSearchQuery] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const highlightSource = useRef<"keyboard" | "mouse">("keyboard");

  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return providerModels;
    const q = searchQuery.toLowerCase();
    return providerModels
      .map((pm) => {
        const matchProvider = (pm.provider.display_name || pm.provider.name).toLowerCase().includes(q);
        const models = matchProvider
          ? pm.models
          : pm.models.filter((m) => m.id.toLowerCase().includes(q));
        return models.length > 0 ? { ...pm, models } : null;
      })
      .filter(Boolean) as ProviderModels[];
  }, [providerModels, searchQuery]);

  const filteredFlat = useMemo(
    () => filtered.flatMap((pm) => pm.models.map((m) => ({ id: m.id, provider: pm.provider.name }))),
    [filtered]
  );

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  // Close on Escape / clear search
  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (searchQuery) {
          setSearchQuery("");
        } else {
          setOpen(false);
        }
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, searchQuery]);

  // Auto-focus search on open
  useEffect(() => {
    if (open) {
      setTimeout(() => searchRef.current?.focus(), 0);
    } else {
      setSearchQuery("");
    }
  }, [open]);

  useEffect(() => {
    if (!open || !listRef.current || highlightSource.current === "mouse") return;
    const el = listRef.current.querySelector(`[data-key="${highlighted}"]`) as HTMLElement | null;
    if (el) {
      const container = listRef.current;
      const containerRect = container.getBoundingClientRect();
      const elRect = el.getBoundingClientRect();
      if (elRect.top < containerRect.top) {
        container.scrollTop -= containerRect.top - elRect.top;
      } else if (elRect.bottom > containerRect.bottom) {
        container.scrollTop += elRect.bottom - containerRect.bottom;
      }
    }
  }, [open, highlighted]);

  const handleSelect = useCallback(
    (modelId: string, providerName: string) => {
      selectedProviderRef.current = providerName;
      onChange(modelId, providerName);
      setOpen(false);
    },
    [onChange]
  );

  const selectedLabel = (() => {
    const provider = selectedProviderRef.current;
    if (provider) {
      const pm = providerModels.find((p) => p.provider.name === provider);
      if (pm) return `${pm.provider.display_name || provider}/${selectedModel}`;
    }
    for (const pm of providerModels) {
      const m = pm.models.find((x) => x.id === selectedModel);
      if (m) return `${pm.provider.display_name || pm.provider.name}/${m.id}`;
    }
    return selectedModel;
  })();

  if (!selectedProviderRef.current && selectedModel) {
    for (const pm of providerModels) {
      if (pm.models.some((m) => m.id === selectedModel)) {
        selectedProviderRef.current = pm.provider.name;
        break;
      }
    }
  }

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!open) {
        if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown") {
          e.preventDefault();
          setOpen(true);
        }
        return;
      }

      if (e.key === "ArrowDown") {
        e.preventDefault();
        const idx = filteredFlat.findIndex((x) => `${x.provider}/${x.id}` === highlighted);
        const next = filteredFlat[idx + 1] ?? filteredFlat[0];
        highlightSource.current = "keyboard";
        setHighlighted(`${next.provider}/${next.id}`);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        const idx = filteredFlat.findIndex((x) => `${x.provider}/${x.id}` === highlighted);
        const prev = filteredFlat[idx - 1] ?? filteredFlat[filteredFlat.length - 1];
        highlightSource.current = "keyboard";
        setHighlighted(`${prev.provider}/${prev.id}`);
      } else if (e.key === "Enter") {
        e.preventDefault();
        const item = filteredFlat.find((x) => `${x.provider}/${x.id}` === highlighted);
        if (item) handleSelect(item.id, item.provider);
      }
    },
    [open, filteredFlat, highlighted, handleSelect]
  );

  if (providerModels.length === 0) {
    return (
      <button
        disabled
        className={cn(
          "text-xs h-7 px-2 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border)]",
          "text-[var(--text-tertiary)] font-mono cursor-not-allowed",
          className
        )}
      >
        No models
      </button>
    );
  }

  return (
    <div ref={containerRef} className={cn("relative", className)}>
      <button
        onClick={() => {
          if (!disabled) {
            setOpen((v) => !v);
            highlightSource.current = "keyboard";
            const key = selectedProviderRef.current
              ? `${selectedProviderRef.current}/${selectedModel}`
              : selectedModel;
            setHighlighted(key);
          }
        }}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        className={cn(
          "flex items-center gap-1.5 text-xs h-7 pl-2.5 pr-1.5 rounded-md",
          "bg-[var(--bg-tertiary)] border border-[var(--border)]",
          "text-[var(--text-primary)] font-mono",
          "focus:outline-none focus:border-[var(--brand)] focus:ring-2 focus:ring-[var(--brand)]/30",
          "transition-colors",
          disabled && "opacity-50 cursor-not-allowed"
        )}
      >
        <span className="truncate max-w-[120px] sm:max-w-[180px]">
          {selectedLabel}
        </span>
        <ChevronDown
          size={13}
          className={cn(
            "text-[var(--text-tertiary)] transition-transform",
            open && "rotate-180"
          )}
        />
      </button>

      {open && (
        <div
          className={cn(
            "absolute bottom-full mb-1.5 right-0 z-50",
            "min-w-[260px] max-w-[340px]",
            "rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)]",
            "shadow-[var(--shadow-lg)] flex flex-col"
          )}
        >
          <div className="p-1.5 border-b border-[var(--border)]">
            <div className="flex items-center gap-1.5 px-2 h-7 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border)] focus-within:border-[var(--brand)] focus-within:ring-2 focus-within:ring-[var(--brand)]/30">
              <Search size={12} className="shrink-0 text-[var(--text-tertiary)]" />
              <input
                ref={searchRef}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Search models…"
                className="flex-1 bg-transparent text-xs font-mono text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none"
              />
            </div>
          </div>
          <div
            ref={listRef}
            className="overflow-y-auto max-h-[380px] py-1"
          >
            {filtered.length === 0 ? (
              <div className="px-3 py-3 text-xs text-[var(--text-tertiary)] text-center">
                No matching models
              </div>
            ) : (
              filtered.map((pm) => (
                <div key={pm.provider.name} className="mb-1 last:mb-0">
                  <div className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                    {pm.provider.display_name || pm.provider.name}
                  </div>
                  {pm.models.map((m) => {
                    const isSelected = m.id === selectedModel && pm.provider.name === selectedProviderRef.current;
                    const isHighlighted = `${pm.provider.name}/${m.id}` === highlighted;
                    return (
                      <button
                        key={`${pm.provider.name}/${m.id}`}
                        data-key={`${pm.provider.name}/${m.id}`}
                        onClick={() => handleSelect(m.id, pm.provider.name)}
                        onMouseEnter={() => { highlightSource.current = "mouse"; setHighlighted(`${pm.provider.name}/${m.id}`); }}
                        className={cn(
                          "w-full flex items-center gap-2 px-3 py-1.5 text-xs font-mono",
                          "text-left transition-colors",
                          isHighlighted && !isSelected && "bg-[var(--bg-tertiary)]",
                          isSelected && "bg-[var(--brand-bg)] text-[var(--brand)]",
                          !isSelected && !isHighlighted && "text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]"
                        )}
                      >
                        <span className="flex-1 truncate">{m.id}</span>
                        {isSelected && (
                          <Check size={13} className="shrink-0 text-[var(--brand)]" />
                        )}
                      </button>
                    );
                  })}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

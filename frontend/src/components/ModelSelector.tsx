import { useState, useRef, useEffect, useCallback } from "react";
import { ChevronDown, Check } from "lucide-react";
import { cn } from "../lib/cn";
import { ProviderModels } from "../hooks/useModelSelector";

interface Props {
  providerModels: ProviderModels[];
  selectedModel: string;
  onChange: (modelId: string) => void;
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
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState<string>(selectedModel);
  const containerRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

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

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open]);

  // Scroll highlighted into view
  useEffect(() => {
    if (!open || !listRef.current) return;
    const el = listRef.current.querySelector(`[data-model="${highlighted}"]`);
    if (el) {
      el.scrollIntoView({ block: "nearest" });
    }
  }, [open, highlighted]);

  const handleSelect = useCallback(
    (modelId: string) => {
      onChange(modelId);
      setOpen(false);
    },
    [onChange]
  );

  // Find display label for selected model
  const selectedLabel = (() => {
    for (const pm of providerModels) {
      const m = pm.models.find((x) => x.id === selectedModel);
      if (m) return m.id;
    }
    return selectedModel;
  })();

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!open) {
        if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown") {
          e.preventDefault();
          setOpen(true);
        }
        return;
      }

      const flat = providerModels.flatMap((pm) => pm.models.map((m) => m.id));
      const idx = flat.indexOf(highlighted);

      if (e.key === "ArrowDown") {
        e.preventDefault();
        const next = flat[idx + 1] ?? flat[0];
        setHighlighted(next);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        const prev = flat[idx - 1] ?? flat[flat.length - 1];
        setHighlighted(prev);
      } else if (e.key === "Enter") {
        e.preventDefault();
        handleSelect(highlighted);
      }
    },
    [open, providerModels, highlighted, handleSelect]
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
            setHighlighted(selectedModel);
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
          ref={listRef}
          className={cn(
            "absolute bottom-full mb-1.5 right-0 z-50",
            "min-w-[220px] max-w-[320px] max-h-[420px] overflow-y-auto",
            "rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)]",
            "shadow-[var(--shadow-lg)] py-1.5"
          )}
        >
          {providerModels.map((pm) => (
            <div key={pm.provider.name} className="mb-1 last:mb-0">
              <div className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                {pm.provider.display_name || pm.provider.name}
              </div>
              {pm.models.map((m) => {
                const isSelected = m.id === selectedModel;
                const isHighlighted = m.id === highlighted;
                return (
                  <button
                    key={m.id}
                    data-model={m.id}
                    onClick={() => handleSelect(m.id)}
                    onMouseEnter={() => setHighlighted(m.id)}
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
          ))}
        </div>
      )}
    </div>
  );
}

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Bold, Italic, Underline, Type, Palette, Sparkles } from "lucide-react";
import { cn } from "../lib/cn";

export interface EditElementStyle {
  bold: boolean;
  italic: boolean;
  underline: boolean;
  fontSize: string;
  color: string;
}

interface Props {
  active: boolean;
  style?: EditElementStyle;
  onStyleChange: (props: Record<string, string | number | boolean>) => void;
  onAIEdit: (instruction: string) => void;
  className?: string;
}

const FONT_SIZES = [10, 12, 14, 16, 18, 20, 24, 28, 32, 40, 48];

export function DocToolbar({ active, style, onStyleChange, onAIEdit, className }: Props) {
  const { t } = useTranslation();
  const [showFontMenu, setShowFontMenu] = useState(false);
  const [showColorMenu, setShowColorMenu] = useState(false);
  const [showAIInput, setShowAIInput] = useState(false);
  const [aiText, setAiText] = useState("");

  const handleSendAI = () => {
    const txt = aiText.trim();
    if (!txt) return;
    onAIEdit(txt);
    setAiText("");
    setShowAIInput(false);
  };

  const btnBase = cn(
    "w-7 h-7 flex items-center justify-center rounded transition-colors",
    active
      ? "text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)]"
      : "text-[var(--text-tertiary)] opacity-40 cursor-not-allowed",
  );

  return (
    <div className={cn("flex items-center gap-0.5 px-2 py-1 border-b border-[var(--border)] bg-[var(--bg-secondary)]", className)}>
      {/* Bold */}
      <button
        disabled={!active}
        onClick={() => active && onStyleChange({ bold: !style?.bold })}
        className={cn(btnBase, style?.bold && active && "bg-[var(--brand-bg)] text-[var(--brand)]")}
        title={t("document.bold")}
      >
        <Bold size={14} />
      </button>

      {/* Italic */}
      <button
        disabled={!active}
        onClick={() => active && onStyleChange({ italic: !style?.italic })}
        className={cn(btnBase, style?.italic && active && "bg-[var(--brand-bg)] text-[var(--brand)]")}
        title={t("document.italic")}
      >
        <Italic size={14} />
      </button>

      {/* Underline */}
      <button
        disabled={!active}
        onClick={() => active && onStyleChange({ underline: !style?.underline })}
        className={cn(btnBase, style?.underline && active && "bg-[var(--brand-bg)] text-[var(--brand)]")}
        title={t("document.underline")}
      >
        <Underline size={14} />
      </button>

      <div className="w-px h-5 bg-[var(--border)] mx-1" />

      {/* Font size */}
      <div className="relative">
        <button
          disabled={!active}
          onClick={() => active && setShowFontMenu((v) => !v)}
          className={cn(btnBase, "gap-1 w-auto px-1.5")}
          title={t("document.fontSize")}
        >
          <Type size={13} />
          <span className="text-[10px]">{style?.fontSize ? Math.round(parseFloat(style.fontSize)) : "—"}</span>
        </button>
        {showFontMenu && active && (
          <div className="absolute top-full left-0 mt-1 z-50 bg-[var(--bg-elevated)] border border-[var(--border)] rounded-lg shadow-[var(--shadow-lg)] py-1 max-h-48 overflow-y-auto">
            {FONT_SIZES.map((sz) => (
              <button
                key={sz}
                onClick={() => {
                  onStyleChange({ size: sz });
                  setShowFontMenu(false);
                }}
                className="w-full text-left px-3 py-1 text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)]"
              >
                {sz}pt
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Color */}
      <div className="relative">
        <button
          disabled={!active}
          onClick={() => active && setShowColorMenu((v) => !v)}
          className={cn(btnBase)}
          title={t("document.color")}
        >
          <Palette size={14} />
        </button>
        {showColorMenu && active && (
          <div className="absolute top-full left-0 mt-1 z-50 bg-[var(--bg-elevated)] border border-[var(--border)] rounded-lg shadow-[var(--shadow-lg)] p-2">
            <div className="grid grid-cols-6 gap-1">
              {["#000000", "#e03131", "#2f9e44", "#1971c2", "#f08c00", "#9c36b5",
                "#495057", "#fa5252", "#40c057", "#228be6", "#fab005", "#ae3ec9"].map((color) => (
                <button
                  key={color}
                  onClick={() => {
                    onStyleChange({ color });
                    setShowColorMenu(false);
                  }}
                  className="w-5 h-5 rounded border border-[var(--border-strong)] hover:scale-110 transition-transform"
                  style={{ backgroundColor: color }}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="flex-1" />

      {/* AI Edit */}
      <div className="relative flex items-center">
        {showAIInput && (
          <input
            type="text"
            value={aiText}
            onChange={(e) => setAiText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSendAI();
              if (e.key === "Escape") { setShowAIInput(false); setAiText(""); }
            }}
            placeholder={t("document.aiEditPlaceholder")}
            autoFocus
            className="w-40 h-7 px-2 text-[11px] rounded bg-[var(--bg-tertiary)] border border-[var(--brand)] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none mr-1"
          />
        )}
        <button
          onClick={() => active && setShowAIInput((v) => !v)}
          disabled={!active}
          className={cn(
            "flex items-center gap-1 h-7 px-2 rounded text-[11px] transition-colors",
            active
              ? "text-[var(--brand)] hover:bg-[var(--brand-bg)]"
              : "text-[var(--text-tertiary)] opacity-40 cursor-not-allowed",
          )}
          title={t("document.aiEditThis")}
        >
          <Sparkles size={12} />
          {t("document.aiEditThis")}
        </button>
      </div>
    </div>
  );
}

import { deleteThemeImage, getThemeImage, IMAGE_PREFIX, putThemeImage } from "./theme-images";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type Theme = "light" | "dark";
export type ThemeMode = Theme | "system";
export const DEFAULT_COLORS = {
  "light": {
    "bg-primary": "#faf7f2",
    "bg-secondary": "#ffffff",
    "bg-tertiary": "#f0ebe2",
    "bg-elevated": "#e6dfd2",
    "text-primary": "#1f1c17",
    "text-secondary": "#6b6358",
    "text-tertiary": "#948a7a",
    "text-on-accent": "#ffffff",
    "text-on-brand": "#ffffff",
    "border": "#e0d8c8",
    "border-subtle": "#ece5d5",
    "border-strong": "#c9bfa9",
    "brand": "#2e8a82",
    "brand-hover": "#3da89e",
    "brand-active": "#1f756d",
    "accent": "#0284c7",
    "accent-hover": "#0ea5e9",
    "accent-2": "#8b6db8",
    "accent-2-hover": "#9d80c8",
    "success": "#4d9659",
    "warning": "#b88a30",
    "danger": "#c8504e",
    "danger-hover": "#d66462",
    "agent-researcher": "#4a82b8",
    "agent-analyst": "#8b6db8",
    "agent-coder": "#4d9659",
    "agent-writer": "#d97706",
    "agent-plan_creater": "#0891b2",
    "code-bg": "#f5f0e5",
    "code-border": "#e0d8c8"
  },
  "dark": {
    "bg-primary": "#1a1814",
    "bg-secondary": "#252320",
    "bg-tertiary": "#33302b",
    "bg-elevated": "#3d3a35",
    "text-primary": "#f5f1e8",
    "text-secondary": "#b8b0a0",
    "text-tertiary": "#8a8275",
    "text-on-accent": "#ffffff",
    "text-on-brand": "#ffffff",
    "border": "#3d3a35",
    "border-subtle": "#2e2c28",
    "border-strong": "#4d4a44",
    "brand": "#3da89e",
    "brand-hover": "#4ec0b5",
    "brand-active": "#2e8a82",
    "accent": "#0ea5e9",
    "accent-hover": "#38bdf8",
    "accent-2": "#b794e0",
    "accent-2-hover": "#c7a8eb",
    "success": "#6ec07a",
    "warning": "#e0b860",
    "danger": "#ef6b6b",
    "danger-hover": "#f58585",
    "agent-researcher": "#6ba0d8",
    "agent-analyst": "#b794e0",
    "agent-coder": "#6ec07a",
    "agent-writer": "#fbbf24",
    "agent-plan_creater": "#22d3ee",
    "code-bg": "#14120f",
    "code-border": "#2e2c28"
  }
} as const;
export type ColorKey = keyof typeof DEFAULT_COLORS.light;
export type ThemeColors = Record<ColorKey, string>;
export interface CustomTheme { id: string; name: string; colors: Record<Theme, ThemeColors>; backgroundImage: string }
const STORAGE_KEY = "crabagent.theme";
const CUSTOM_KEY = "crabagent.customThemes";
const ACTIVE_KEY = "crabagent.activeTheme";
const colorKeys = Object.keys(DEFAULT_COLORS.light) as ColorKey[];
const isColor = (value: unknown): value is string => typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value);
export function validImage(value: string): boolean {
  if (!value || /^indexeddb:[a-z0-9-]+$/i.test(value)) return true;
  if (/^data:image\/(png|jpeg|gif|webp);base64,[a-z0-9+/=]+$/i.test(value)) return true;
  try { return ["https:", "http:"].includes(new URL(value).protocol); } catch { return false; }
}
export function parseThemes(raw: string | null): CustomTheme[] {
  try {
    const data: unknown = JSON.parse(raw || "[]");
    if (!Array.isArray(data)) return [];
    return data.flatMap((item: any) => {
      if (!item || typeof item.id !== "string" || typeof item.name !== "string" || typeof item.backgroundImage !== "string" || !validImage(item.backgroundImage) || !item.colors) return [];
      const legacy = ["brand", "accent", "background", "text"].every(key => isColor(item.colors[key]));
      const palettes = {} as Record<Theme, ThemeColors>;
      for (const mode of ["light", "dark"] as const) {
        if (legacy) {
          palettes[mode] = { ...DEFAULT_COLORS[mode], brand: item.colors.brand, accent: item.colors.accent, "bg-primary": item.colors.background, "text-primary": item.colors.text };
        } else {
          const palette = item.colors[mode];
          if (!palette || !colorKeys.every(key => isColor(palette[key]))) return [];
          palettes[mode] = Object.fromEntries(colorKeys.map(key => [key, palette[key]])) as ThemeColors;
        }
      }
      return [{ id: item.id, name: item.name, backgroundImage: item.backgroundImage, colors: palettes }];
    });
  } catch { return []; }
}
interface ThemeContextValue {
  theme: Theme; mode: ThemeMode; setTheme: (t: Theme) => void; setMode: (t: ThemeMode) => void; toggleTheme: () => void;
  colors: ThemeColors | undefined; themes: CustomTheme[]; activeId: string; selectTheme: (id: string) => void; saveTheme: (theme: CustomTheme, image?: Blob) => Promise<void>; deleteTheme: (id: string) => Promise<void>; imageError: string;
}
const ThemeContext = createContext<ThemeContextValue | null>(null);
const read = (key: string) => { try { return localStorage.getItem(key); } catch { return null; } };
function initialMode(): ThemeMode { const value = read(STORAGE_KEY); return value === "light" || value === "dark" || value === "system" ? value : "system"; }
function systemTheme(): Theme { return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark"; }
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(initialMode);
  const [system, setSystem] = useState<Theme>(systemTheme);
  const [themes, setThemes] = useState<CustomTheme[]>(() => parseThemes(read(CUSTOM_KEY)));
  const [activeId, setActiveId] = useState(() => read(ACTIVE_KEY) || "");
  const [imageUrl, setImageUrl] = useState("");
  const [imageError, setImageError] = useState("");
  const theme = mode === "system" ? system : mode;
  const active = themes.find(item => item.id === activeId);
  useEffect(() => {
    const media = window.matchMedia?.("(prefers-color-scheme: light)");
    if (!media) return;
    const changed = () => setSystem(media.matches ? "light" : "dark");
    media.addEventListener("change", changed);
    return () => media.removeEventListener("change", changed);
  }, []);
  useEffect(() => {
    const image = active?.backgroundImage || "";
    setImageUrl("");
    setImageError("");
    if (!image.startsWith(IMAGE_PREFIX)) { setImageUrl(image); return; }
    let cancelled = false;
    let url = "";
    getThemeImage(image.slice(IMAGE_PREFIX.length)).then(blob => {
      if (!blob) throw new Error("Image not found");
      if (!cancelled) { url = URL.createObjectURL(blob); setImageUrl(url); }
    }).catch(() => { if (!cancelled) setImageError("背景图片读取失败，请检查浏览器存储或重新上传。"); });
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url); };
  }, [active?.backgroundImage]);
  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-theme", theme);
    const colors = active?.colors[theme];
    for (const key of colorKeys) {
      if (colors) root.style.setProperty(`--${key}`, colors[key]); else root.style.removeProperty(`--${key}`);
    }
    const derived: Record<string, [ColorKey, number]> = {
      "brand-bg": ["brand", 12], "brand-bg-strong": ["brand", 22], "brand-border": ["brand", 35],
      "accent-bg": ["accent", 12], "accent-border": ["accent", 30], "accent-2-bg": ["accent-2", 12],
      "success-bg": ["success", 12], "success-border": ["success", 30], "warning-bg": ["warning", 12], "warning-border": ["warning", 30],
      "danger-bg": ["danger", 12], "danger-border": ["danger", 30],
      ...Object.fromEntries((["researcher", "analyst", "coder", "writer", "plan_creater"] as const).map(name => [`agent-${name}-bg`, [`agent-${name}`, 12]])),
    };
    for (const [key, [base, opacity]] of Object.entries(derived)) {
      if (colors) root.style.setProperty(`--${key}`, `color-mix(in srgb, var(--${base}) ${opacity}%, transparent)`); else root.style.removeProperty(`--${key}`);
    }
    if (imageUrl) root.style.setProperty("--custom-background-image", `url(${JSON.stringify(imageUrl)})`);
    else root.style.removeProperty("--custom-background-image");
  }, [theme, active, imageUrl]);
  const setMode = (value: ThemeMode) => { localStorage.setItem(STORAGE_KEY, value); setModeState(value); };
  const selectTheme = (id: string) => { localStorage.setItem(ACTIVE_KEY, id); setActiveId(id); };
  const saveTheme = async (item: CustomTheme, image?: Blob) => {
    if (!item.name.trim() || !validImage(item.backgroundImage) || !( ["light", "dark"] as const).every(mode => item.colors[mode] && colorKeys.every(key => isColor(item.colors[mode][key])))) throw new Error("Invalid theme");
    const previous = themes.find(t => t.id === item.id)?.backgroundImage || "";
    let newKey = "";
    // Migrate legacy data URLs only when the theme is saved, preserving them on failure.
    if (!image && item.backgroundImage.startsWith("data:")) image = await (await fetch(item.backgroundImage)).blob();
    if (image) {
      newKey = crypto.randomUUID();
      await putThemeImage(newKey, image);
      item = { ...item, backgroundImage: IMAGE_PREFIX + newKey };
    }
    const next = [...themes.filter(t => t.id !== item.id), item];
    try {
      localStorage.setItem(CUSTOM_KEY, JSON.stringify(next));
    } catch (error) {
      if (newKey) await deleteThemeImage(newKey).catch(() => {});
      throw error;
    }
    setThemes(next);
    if (previous.startsWith(IMAGE_PREFIX) && previous !== item.backgroundImage) void deleteThemeImage(previous.slice(IMAGE_PREFIX.length)).catch(() => {});
    selectTheme(item.id);
  };
  const deleteTheme = async (id: string) => {
    const previous = themes.find(t => t.id === id)?.backgroundImage || "";
    const next = themes.filter(t => t.id !== id);
    localStorage.setItem(CUSTOM_KEY, JSON.stringify(next)); setThemes(next);
    if (activeId === id) selectTheme("");
    if (previous.startsWith(IMAGE_PREFIX)) await deleteThemeImage(previous.slice(IMAGE_PREFIX.length));
  };
  return <ThemeContext.Provider value={{ theme, mode, setTheme: setMode, setMode, toggleTheme: () => setMode(theme === "dark" ? "light" : "dark"), colors: active?.colors[theme], themes, activeId, selectTheme, saveTheme, deleteTheme, imageError }}>{children}</ThemeContext.Provider>;
}
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside <ThemeProvider>");
  return ctx;
}

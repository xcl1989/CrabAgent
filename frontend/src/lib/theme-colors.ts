import { useTheme, type Theme } from "./theme";

export interface ThemeColors {
  brand: string;
  brandHover: string;
  brandActive: string;
  accent: string;
  accentHover: string;
  accent2: string;
  accent2Hover: string;
  success: string;
  warning: string;
  danger: string;
  dangerHover: string;
  bgPrimary: string;
  bgSecondary: string;
  bgTertiary: string;
  bgElevated: string;
  border: string;
  borderStrong: string;
  textPrimary: string;
  textSecondary: string;
  textTertiary: string;
  agentResearcher: string;
  agentAnalyst: string;
  agentCoder: string;
  agentWriter: string;
}

const DARK: ThemeColors = {
  brand: "#3da89e",
  brandHover: "#4ec0b5",
  brandActive: "#2e8a82",
  accent: "#0ea5e9",
  accentHover: "#38bdf8",
  accent2: "#b794e0",
  accent2Hover: "#c7a8eb",
  success: "#6ec07a",
  warning: "#e0b860",
  danger: "#ef6b6b",
  dangerHover: "#f58585",
  bgPrimary: "#1a1814",
  bgSecondary: "#252320",
  bgTertiary: "#33302b",
  bgElevated: "#3d3a35",
  border: "#3d3a35",
  borderStrong: "#4d4a44",
  textPrimary: "#f5f1e8",
  textSecondary: "#b8b0a0",
  textTertiary: "#8a8275",
  agentResearcher: "#6ba0d8",
  agentAnalyst: "#b794e0",
  agentCoder: "#6ec07a",
  agentWriter: "#fbbf24",
};

const LIGHT: ThemeColors = {
  brand: "#2e8a82",
  brandHover: "#3da89e",
  brandActive: "#1f756d",
  accent: "#0284c7",
  accentHover: "#0ea5e9",
  accent2: "#8b6db8",
  accent2Hover: "#9d80c8",
  success: "#4d9659",
  warning: "#b88a30",
  danger: "#c8504e",
  dangerHover: "#d66462",
  bgPrimary: "#faf7f2",
  bgSecondary: "#ffffff",
  bgTertiary: "#f0ebe2",
  bgElevated: "#e6dfd2",
  border: "#e0d8c8",
  borderStrong: "#c9bfa9",
  textPrimary: "#1f1c17",
  textSecondary: "#6b6358",
  textTertiary: "#948a7a",
  agentResearcher: "#4a82b8",
  agentAnalyst: "#8b6db8",
  agentCoder: "#4d9659",
  agentWriter: "#d97706",
};

export function getThemeColors(theme: Theme): ThemeColors {
  return theme === "light" ? LIGHT : DARK;
}

export function useThemeColors(): ThemeColors {
  const { theme } = useTheme();
  return getThemeColors(theme);
}

export function agentColor(name: string, colors: ThemeColors): string {
  switch (name) {
    case "researcher":
      return colors.agentResearcher;
    case "analyst":
      return colors.agentAnalyst;
    case "coder":
      return colors.agentCoder;
    case "writer":
      return colors.agentWriter;
    default:
      return colors.textTertiary;
  }
}

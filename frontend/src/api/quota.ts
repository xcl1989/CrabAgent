import { api } from "./client";

// ── DeepSeek ──

export interface DeepSeekBalanceInfo {
  currency: string;
  total: string;
  granted: string;
  topped_up: string;
}

export interface DeepSeekQuota {
  is_available: boolean;
  balances: DeepSeekBalanceInfo[];
}

// ── Zhipu ──

export interface ZhipuTokenLimit {
  percentage: number;
  unit: number;
  number: number;
  nextResetTime?: number;
  label: string;
}

export interface ZhipuTimeLimit {
  percentage: number;
  usage: number;
  currentValue: number;
  remaining: number;
  nextResetTime?: number;
  usageDetails?: { code: string; usage: number }[];
}

export interface ZhipuQuota {
  level: string;
  token_limits: ZhipuTokenLimit[];
  time_limit: ZhipuTimeLimit | null;
}

// ── Unified ──

export interface ProviderQuota {
  provider_type: "deepseek" | "zhipu";
  raw: Record<string, unknown>;
  summary: DeepSeekQuota | ZhipuQuota;
}

export function getProviderQuota(name: string): Promise<ProviderQuota> {
  return api.get("/providers/quota", { name });
}

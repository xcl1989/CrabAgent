import { api } from "./client";

export interface DeviceCodeInfo {
  device_auth_id: string;
  user_code: string;
  verification_url: string;
  interval: number;
  expires_in: number;
}

export interface ChatGPTAuthStatus {
  authenticated: boolean;
  access_token_preview?: string;
  expires_at?: number | null;
  account_id?: string | null;
  error?: string | null;
}

export interface ChatGPTAccountInfo {
  plan?: string | null;
  email?: string | null;
  name?: string | null;
  account_id?: string | null;
  rate_limits?: {
    active_limit?: string;
    plan?: string;
    primary?: {
      used_percent?: number | null;
      window_hours?: number | null;
      reset_after_minutes?: number | null;
    };
    secondary?: {
      used_percent?: number | null;
      window_days?: number | null;
      reset_after_hours?: number | null;
    };
    credits?: {
      has_credits?: boolean;
      balance?: string;
      unlimited?: boolean;
    };
    banked_resets?: {
      available_count?: number;
      credits?: ResetCredit[];
    };
    error?: string;
  } | null;
  raw?: Record<string, unknown> | null;
}

export interface ResetCredit {
  id: string;
  reset_type?: string;
  available_count?: number;
  expires_at?: string | null;
  [key: string]: unknown;
}

export interface ResetCreditsResponse {
  credits: ResetCredit[];
  available_count: number;
  error?: string;
}

export function getAuthStatus(): Promise<ChatGPTAuthStatus> {
  return api.get("/chatgpt/auth/status");
}

export function startDeviceCode(): Promise<DeviceCodeInfo> {
  return api.post("/chatgpt/auth/device-code", {});
}

export function pollDeviceAuth(
  device_auth_id: string,
  user_code: string,
): Promise<ChatGPTAuthStatus> {
  return api.post(`/chatgpt/auth/poll?device_auth_id=${encodeURIComponent(device_auth_id)}&user_code=${encodeURIComponent(user_code)}`, {});
}

export function logout(): Promise<void> {
  return api.post("/chatgpt/auth/logout", {});
}

export function getAccountInfo(): Promise<ChatGPTAccountInfo> {
  return api.get("/chatgpt/account");
}

export function listModels(): Promise<{ id: string; owned_by: string }[]> {
  return api.get("/chatgpt/models");
}

export function getResetCredits(): Promise<ResetCreditsResponse> {
  return api.get("/chatgpt/reset-credits");
}

export function consumeResetCredit(credit_id: string): Promise<{ status: string; result?: unknown }> {
  return api.post("/chatgpt/reset-credits/consume", { credit_id });
}

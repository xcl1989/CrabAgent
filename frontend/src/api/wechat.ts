import { api } from "./client";

export interface WeChatStatus {
  logged_in: boolean;
  enabled: boolean;
  account_id: string;
  auto_reply: boolean;
  workspace: string;
  allowed_users: string[];
  notify_task_overdue: boolean;
  notify_schedule_result: boolean;
  notify_email_summary: boolean;
  notify_target_user: string;
}

export interface QRCodeResponse {
  qrcode: string;
  qrcode_img_base64: string;
  qrcode_url: string;
}

export interface QRCodeStatusResponse {
  status: string; // wait | scanned | confirmed | expired | error
  logged_in: boolean;
}

export interface WeChatConversation {
  session_id: string;
  title: string;
  workspace: string;
  model: string;
  created_at: string | null;
  updated_at: string | null;
  message_count: number;
  last_message: string;
}

export function getStatus(): Promise<WeChatStatus> {
  return api.get("/wechat/status");
}

export function startQRLogin(): Promise<QRCodeResponse> {
  return api.post("/wechat/qrcode", {});
}

export function pollQRStatus(): Promise<QRCodeStatusResponse> {
  return api.get("/wechat/qrcode/status");
}

export function logout(): Promise<{ success: boolean }> {
  return api.post("/wechat/logout", {});
}

export function updateConfig(config: Partial<{
  enabled: boolean;
  auto_reply: boolean;
  workspace: string;
  allowed_users: string[];
  notify_task_overdue: boolean;
  notify_schedule_result: boolean;
  notify_email_summary: boolean;
  notify_target_user: string;
}>): Promise<{ success: boolean }> {
  return api.put("/wechat/config", config);
}

export function sendTestMessage(text: string): Promise<{ success: boolean }> {
  return api.post("/wechat/test", { text });
}

export function getConversations(): Promise<WeChatConversation[]> {
  return api.get("/wechat/conversations");
}

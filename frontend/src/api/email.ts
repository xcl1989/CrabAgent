import { api } from "./client";

export interface EmailConfig {
  imap_host: string;
  imap_port: number;
  imap_user: string;
  imap_pass: string;
  smtp_host: string;
  smtp_port: number;
  smtp_user: string;
  smtp_pass: string;
  check_interval: number;
  enabled: boolean;
}

export interface EmailItem {
  id: string;
  subject: string;
  from: string;
  date: string;
  body: string;
  raw_message_id: string;
}

export interface TaskSummary {
  total: number;
  pending: number;
  overdue: number;
  done_today: number;
}

export interface DigestResponse {
  digest: string;
  sent_to: string;
  summary: TaskSummary;
}

export interface RemindResponse {
  overdue: number;
  due_soon: number;
  items: Array<{
    id: number;
    title: string;
    deadline: string | null;
    priority: string;
  }>;
  sent_to: string;
}

export function getEmailConfig(): Promise<EmailConfig | Record<string, never>> {
  return api.get("/email/config");
}

export function saveEmailConfig(config: Partial<EmailConfig>): Promise<EmailConfig> {
  return api.post("/email/config", config);
}

export function testEmailConnection(): Promise<{ result: string }> {
  return api.post("/email/test", {});
}

export function checkNewEmails(limit = 5): Promise<{ emails: EmailItem[] }> {
  return api.post(`/email/check?limit=${limit}`, {});
}

export function sendDailyDigest(to = ""): Promise<DigestResponse> {
  return api.post("/email/daily-digest", { to });
}

export function sendTaskReminder(to = ""): Promise<RemindResponse> {
  return api.post("/email/task-remind", { to });
}

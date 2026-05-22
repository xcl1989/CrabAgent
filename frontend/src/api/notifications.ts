import { api } from "./client";

export interface Notification {
  id: number;
  title: string;
  body: string;
  conversation_id: string;
  read: boolean;
  created_at: string;
}

export function listNotifications(): Promise<Notification[]> {
  return api.get("/notifications");
}

export function unreadCount(): Promise<{ count: number }> {
  return api.get("/notifications/unread-count");
}

export function markRead(id: number): Promise<{ status: string }> {
  return api.post(`/notifications/${id}/read`, {});
}

export function markAllRead(): Promise<{ status: string }> {
  return api.post("/notifications/read-all", {});
}

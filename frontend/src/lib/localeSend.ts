import { api } from "../api/client";

export async function sendWithLocale<T>(
  sessionId: string,
  locale: string,
  draft: T,
  send: (draft: T) => Promise<void>,
  onReady: () => void,
) {
  await api.patch("/auth/user", { locale });
  await api.post(`/sessions/${sessionId}/reset-system-prompt`, {});
  onReady();
  await send(draft);
}

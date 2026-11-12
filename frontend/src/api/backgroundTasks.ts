import { api } from "./client";

export interface BackgroundTask {
  id: string;
  agent_name: string;
  task: string;
  status: string;
  result?: string;
}

const path = (session: string) => `/sessions/${encodeURIComponent(session)}/background-tasks`;
export const listBackgroundTasks = (session: string) =>
  api.get<{ branch: string; tasks: BackgroundTask[] }>(path(session));
export const getBackgroundTask = (session: string, branch: string, id: string) =>
  api.get<BackgroundTask>(`${path(session)}/${encodeURIComponent(id)}`, { branch });
export const cancelBackgroundTask = (session: string, branch: string, id: string) =>
  api.post<BackgroundTask>(`${path(session)}/${encodeURIComponent(id)}/cancel?${new URLSearchParams({ branch })}`, {});

export interface BackgroundGroup {
  id: string;
  status: string;
  steps?: { step_id: string; agent_name: string; task: string; depends_on: string[]; status: string; job_id: string; result: string }[];
  summary?: { status: string; text: string } | null;
}
export const listBackgroundGroups = (session: string) =>
  api.get<{ branch: string; groups: BackgroundGroup[] }>(`${path(session)}/groups`);
export const getBackgroundGroup = (session: string, branch: string, id: string) =>
  api.get<BackgroundGroup>(`${path(session)}/groups/${encodeURIComponent(id)}`, { branch });
export const cancelBackgroundGroup = (session: string, branch: string, id: string) =>
  api.post<BackgroundGroup>(`${path(session)}/groups/${encodeURIComponent(id)}/cancel?${new URLSearchParams({ branch })}`, {});

export interface SemanticSummary { status: string; text: string }
const summaryPath = (session: string, id: string) => `${path(session)}/groups/${encodeURIComponent(id)}/semantic-summary`;
export const getSemanticSummary = (session: string, branch: string, id: string) =>
  api.get<{ summary: SemanticSummary | null }>(summaryPath(session, id), { branch });
export interface SummaryProvider { name: string; type: string; model: string; endpoint: string; proxy: string; binding: string }
export const getSummaryProvider = (session: string, branch: string, id: string) =>
  api.get<SummaryProvider>(`${summaryPath(session, id)}/provider`, { branch });
export const startSemanticSummary = (session: string, branch: string, id: string, password: string, binding: string) =>
  api.post<{ summary: SemanticSummary | null }>(`${summaryPath(session, id)}?${new URLSearchParams({ branch })}`, { consent: true, password, binding });
export const cancelSemanticSummary = (session: string, branch: string, id: string) =>
  api.post<{ summary: SemanticSummary | null }>(`${summaryPath(session, id)}/cancel?${new URLSearchParams({ branch })}`, {});

export const deleteSemanticSummary = (session: string, branch: string, id: string) =>
  api.del<{ deleted: boolean }>(`${summaryPath(session, id)}?${new URLSearchParams({ branch })}`);

export interface DeliveryCard { id: string; status: string; steps: { step_id: string; status: string; result: string }[] }
export const listDeliveries = (session: string) => api.get<{ branch: string; deliveries: DeliveryCard[] }>(`${path(session)}/deliveries`);
export const authorizeDelivery = (session: string, branch: string, id: string) => api.post(`${path(session)}/groups/${encodeURIComponent(id)}/delivery?${new URLSearchParams({ branch })}`, { consent: true });
export const revokeDelivery = (session: string, branch: string, id: string) => api.del(`${path(session)}/groups/${encodeURIComponent(id)}/delivery?${new URLSearchParams({ branch })}`);

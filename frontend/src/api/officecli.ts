import { api } from "./client";

export interface OfficeCliStatus {
  status: "not_found" | "installing" | "ready" | "failed";
  message: string;
  progress: number;
  available: boolean;
  version?: string;
}

export interface OfficeCliPerfStats {
  available: boolean;
  version?: string;
  stats: Record<string, { count: number; min_ms: number; max_ms: number; avg_ms: number }>;
}

export async function getOfficeCliStatus(): Promise<OfficeCliStatus> {
  return api.get("/officecli/status");
}

export async function getOfficeCliPerf(): Promise<OfficeCliPerfStats> {
  return api.get("/officecli/perf");
}

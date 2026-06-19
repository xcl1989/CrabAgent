import { api } from "./client";

export interface OfficeCliStatus {
  status: "not_found" | "installing" | "ready" | "failed";
  message: string;
  progress: number;
  available: boolean;
  version?: string;
}

export async function getOfficeCliStatus(): Promise<OfficeCliStatus> {
  return api.get("/officecli/status");
}

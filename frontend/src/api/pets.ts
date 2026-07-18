import { api } from "./client";

export interface PetListItem {
  id: string;
  displayName: string;
  description: string;
  is_builtin: boolean;
  created_at: string;
}

export interface PetDetail {
  id: string;
  displayName: string;
  description: string;
  spritesheetPath: string;
  width: number;
  height: number;
  columns: number;
  rows: number;
  frame_counts: Record<string, number>;
  frame_rates: Record<string, number>;
  type: "svg" | "spritesheet";
  is_builtin: boolean;
}

export interface CreatePetRequest {
  id: string;
  displayName: string;
  description?: string;
  spritesheetPath?: string;
  width?: number;
  height?: number;
  columns?: number;
  rows?: number;
  frame_counts?: Record<string, number>;
  frame_rates?: Record<string, number>;
  type?: "svg" | "spritesheet";
}

export async function listPets(): Promise<PetListItem[]> {
  return api.get<PetListItem[]>("/pets");
}

export async function getPet(id: string): Promise<PetDetail> {
  return api.get<PetDetail>(`/pets/${id}`);
}

export async function createPet(req: CreatePetRequest): Promise<PetDetail> {
  return api.post<PetDetail>("/pets", req);
}

export async function uploadSpritesheet(
  petId: string,
  file: File,
): Promise<{ ok: boolean; spritesheetPath: string }> {
  const form = new FormData();
  form.append("file", file);
  return api.post<{ ok: boolean; spritesheetPath: string }>(`/pets/${petId}/upload`, form as unknown as Record<string, unknown>);
}

export function getSpritesheetUrl(petId: string): string {
  const token = localStorage.getItem("crab_token") || "";
  return `/api/pets/${petId}/spritesheet?token=${encodeURIComponent(token)}`;
}

export async function deletePet(id: string): Promise<void> {
  return api.del(`/pets/${id}`);
}

export async function setActivePet(id: string): Promise<void> {
  await api.put("/settings", { settings: { active_pet_id: id } });
}

export async function getActivePet(): Promise<string | null> {
  const settings = await api.get<Record<string, string>>("/settings");
  return settings.active_pet_id || null;
}

export interface GeneratePetResponse {
  id: string;
  displayName: string;
  status: string;
}

export interface GenerationStatusResponse {
  id: string;
  status: "generating" | "ready" | "error";
  displayName: string;
  description: string;
}

export async function generatePet(
  prompt: string,
  style: string = "pixel",
  referenceFile?: File | null,
  preserveReferenceStyle: boolean = false,
): Promise<GeneratePetResponse> {
  const form = new FormData();
  form.append("prompt", prompt);
  form.append("style", style);
  form.append("preserve_reference_style", String(preserveReferenceStyle));
  if (referenceFile) {
    form.append("reference", referenceFile);
  }
  return api.post<GeneratePetResponse>("/pets/generate", form as unknown as Record<string, unknown>);
}

export async function getGenerationStatus(petId: string): Promise<GenerationStatusResponse> {
  return api.get<GenerationStatusResponse>(`/pets/generate/${petId}/status`);
}

export interface ActiveJob {
  pet_id: string;
  step: number;
  total_steps: number;
  step_name: string;
  step_label: string;
  status: string;
  prompt: string;
  style: string;
  updated_at: number;
}

export async function getActiveGenerations(): Promise<ActiveJob[]> {
  const resp = await api.get<{ jobs: ActiveJob[] }>("/pets/generate/active");
  return resp.jobs || [];
}

export interface GenerationProgress {
  status: "running" | "done" | "error" | "idle";
  step: number;
  total_steps: number;
  step_name: string;
  step_label: string;
  prompt?: string;
  style?: string;
  error?: string;
}

export function subscribeGenerationProgress(
  petId: string,
  onProgress: (progress: GenerationProgress) => void,
  onError?: (error: Event) => void,
): EventSource {
  const token = localStorage.getItem("crab_token") || "";
  const url = `/api/pets/generate/${petId}/progress?token=${encodeURIComponent(token)}`;
  const es = new EventSource(url);
  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data) as GenerationProgress;
      onProgress(data);
    } catch {
      // ignore parse errors
    }
  };
  if (onError) es.onerror = onError;
  return es;
}
import { api } from "./client";

export interface Provider {
  name: string;
  display_name: string;
  type: string;
  is_default: boolean;
  enabled: boolean;
  base_url: string;
  api_key_preview: string;
}

export interface CatalogEntry {
  type: string;
  display_name: string;
  base_url: string;
}

export interface ModelInfo {
  id: string;
  owned_by: string;
}

export function listProviders(): Promise<Provider[]> {
  return api.get("/providers");
}

export function getCatalog(): Promise<CatalogEntry[]> {
  return api.get("/providers/catalog");
}

export function createProvider(data: {
  name: string;
  type: string;
  api_key: string;
  display_name?: string;
  base_url?: string;
  is_default?: boolean;
}): Promise<Provider> {
  return api.post("/providers", data);
}

export function updateProvider(
  name: string,
  data: { display_name?: string; api_key?: string; base_url?: string; enabled?: boolean; is_default?: boolean },
): Promise<Provider> {
  return api.patch(`/providers/${name}`, data);
}

export function deleteProvider(name: string): Promise<void> {
  return api.del(`/providers/${name}`);
}

export function getProviderModels(name: string): Promise<ModelInfo[]> {
  return api.get(`/providers/${name}/models`);
}

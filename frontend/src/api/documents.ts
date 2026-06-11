import { api } from "./client";

export interface DocFileInfo {
  name: string;
  path: string;
  size: number;
  modified: number;
  type: string;
  previewable: boolean;
}

export interface DocListResponse {
  files: DocFileInfo[];
  workspace: string;
  dir: string;
}

export interface DocPreviewResponse {
  html: string;
  file: string;
  name: string;
}

export function listDocuments(workspace = ""): Promise<DocListResponse> {
  const params = workspace ? { workspace } : undefined;
  return api.get("/documents", params);
}

export async function uploadDocument(
  file: File,
  workspace = "",
): Promise<{ status: string; file: string; size: number; path: string }> {
  const formData = new FormData();
  formData.append("file", file);
  if (workspace) formData.append("workspace", workspace);
  const res = await fetch("/api/documents/upload", {
    method: "POST",
    body: formData,
    headers: api.getToken()
      ? { Authorization: `Bearer ${api.getToken()!}` }
      : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export function getDownloadUrl(path: string): string {
  const params = new URLSearchParams({ path });
  const token = api.getToken();
  if (token) params.set("token", token);
  return `/api/documents/download?${params.toString()}`;
}

export async function getPreview(
  path: string,
  workspace = "",
): Promise<DocPreviewResponse> {
  const params: Record<string, string> = { path };
  if (workspace) params.workspace = workspace;
  return api.get("/documents/preview", params);
}

export function saveDocument(
  path: string,
  contentBase64: string,
  workspace = "",
): Promise<{ status: string; file: string; size: number }> {
  return api.post("/documents/save", { path, content: contentBase64, workspace });
}

export async function deleteDocument(
  path: string,
  workspace = "",
): Promise<{ status: string; file: string }> {
  const params: Record<string, string> = { path };
  if (workspace) params.workspace = workspace;
  const res = await fetch(`/api/documents?${new URLSearchParams(params)}`, {
    method: "DELETE",
    headers: api.getToken()
      ? { Authorization: `Bearer ${api.getToken()!}`, "Content-Type": "application/json" }
      : { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

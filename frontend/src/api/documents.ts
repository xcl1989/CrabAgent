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

export interface QuickEditTextRequest {
  path: string;
  old_text: string;
  new_text: string;
  workspace?: string;
}

export interface QuickEditTextResponse {
  status: string;
  preview_html: string | null;
  message: string;
}

export function quickEditText(
  req: QuickEditTextRequest,
): Promise<QuickEditTextResponse> {
  return api.post("/documents/quick-edit/text", req);
}

// ── Quick Edit: Style ─────────────────────────────────────────────

export interface StyleChange {
  element: string;
  props: Record<string, string | number | boolean>;
}

export interface QuickEditStyleRequest {
  path: string;
  workspace?: string;
  changes: StyleChange[];
}

export interface QuickEditStyleResponse {
  status: string;
  preview_html: string | null;
  results: Array<{ element: string; success: boolean; error?: string }>;
  message: string;
}

export function quickEditStyle(
  req: QuickEditStyleRequest,
): Promise<QuickEditStyleResponse> {
  return api.post("/documents/quick-edit/style", req);
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

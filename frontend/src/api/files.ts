import { api } from "./client";

export interface FileEntry {
  name: string;
  path: string;
  type: "file" | "directory";
  children?: FileEntry[];
}

export interface FileContent {
  path: string;
  content: string;
  truncated: boolean;
  message?: string;
}

export async function getTree(path: string = "", depth: number = 5, absolute: boolean = false): Promise<FileEntry[]> {
  const params = new URLSearchParams();
  if (path) params.set("path", path);
  params.set("depth", String(depth));
  if (absolute) params.set("absolute", "true");
  return api.get<FileEntry[]>(`/files/tree?${params}`);
}

export async function searchFiles(query: string, absolute: boolean = false, limit: number = 200, path?: string, signal?: AbortSignal): Promise<FileEntry[]> {
  const params: Record<string, string> = { q: query, limit: String(limit) };
  if (absolute) params.absolute = "true";
  if (path) params.path = path;
  const res = await api.get<{ results: FileEntry[]; total: number }>(`/files/search`, params, signal);
  return res.results;
}

export async function readFile(path: string, absolute: boolean = false): Promise<FileContent> {
  const params = new URLSearchParams();
  params.set("path", path);
  if (absolute) params.set("absolute", "true");
  return api.get<FileContent>(`/files/read?${params}`);
}

const IMAGE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp", ".avif"]);

export function isImageFile(path: string): boolean {
  const ext = path.substring(path.lastIndexOf(".")).toLowerCase();
  return IMAGE_EXTENSIONS.has(ext);
}

export function getImageUrl(path: string, absolute: boolean = false): string {
  const token = localStorage.getItem("crab_token") || "";
  const params = new URLSearchParams();
  params.set("path", path);
  params.set("absolute", String(absolute));
  params.set("token", token);
  return `/api/files/image?${params}`;
}

let _activePreviewServer: { filePath: string; token: string; url: string } | null = null;

export function getActivePreviewUrl(): string | null {
  return _activePreviewServer?.url ?? null;
}

export function clearPreviewServer(): void {
  _activePreviewServer = null;
}

export async function startPreviewServer(filePath: string): Promise<{ token: string; url: string }> {
  if (_activePreviewServer) {
    try {
      await api.post(`/files/stop-server?token=${encodeURIComponent(_activePreviewServer.token)}`, {});
    } catch {}
  }
  const dir = filePath.substring(0, filePath.lastIndexOf("/"));
  const fileName = filePath.split("/").pop() || "index.html";
  const res = await api.post<{ token: string; url: string }>(`/files/serve-dir?path=${encodeURIComponent(dir)}`, {});
  _activePreviewServer = { filePath, token: res.token, url: `${res.url}/${encodeURIComponent(fileName)}` };
  return _activePreviewServer;
}

export async function stopPreviewServer(): Promise<void> {
  if (_activePreviewServer) {
    try {
      await api.post(`/files/stop-server?token=${encodeURIComponent(_activePreviewServer.token)}`, {});
    } catch {}
    _activePreviewServer = null;
  }
}

export interface GitChange {
  status: string;
  file: string;
}

export interface GitStatusResult {
  is_git: boolean;
  changes: GitChange[];
  diff_summary?: string;
  error?: string;
}

export interface GitDiffResult {
  is_git: boolean;
  diff: string;
  truncated?: boolean;
  error?: string;
}

export async function getGitStatus(workspace?: string): Promise<GitStatusResult> {
  const params = new URLSearchParams();
  if (workspace) params.set("workspace", workspace);
  return api.get<GitStatusResult>(`/files/git-status?${params}`);
}

export async function getGitDiff(path?: string, cached?: boolean, workspace?: string): Promise<GitDiffResult> {
  const params = new URLSearchParams();
  if (path) params.set("path", path);
  if (cached) params.set("cached", "true");
  if (workspace) params.set("workspace", workspace);
  return api.get<GitDiffResult>(`/files/git-diff?${params}`);
}

export async function saveFile(path: string, content: string, absolute?: boolean): Promise<{ status: string; path: string; size: number }> {
  return api.post("/files/write", { path, content, absolute });
}

// ── General file upload ────────────────────────────────────────────

export async function uploadFile(
  file: File,
): Promise<{ status: string; file: string; size: number; path: string }> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch("/api/files/upload", {
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

// ── File management: delete / rename / create / download ───────────

export async function deleteFile(path: string, absolute?: boolean): Promise<{ status: string }> {
  return api.del("/files/manage", { path, absolute });
}

export async function renameFile(oldPath: string, newPath: string, absolute?: boolean): Promise<{ status: string }> {
  return api.post("/files/rename", { old_path: oldPath, new_path: newPath, absolute });
}

export async function createEntry(path: string, entryType: "file" | "directory", absolute?: boolean): Promise<{ status: string }> {
  return api.post("/files/create", { path, entry_type: entryType, absolute });
}

export async function moveEntries(paths: string[], destination: string, absolute?: boolean): Promise<{ status: string; moved: number }> {
  return api.post("/files/move", { paths, destination, absolute });
}

export function getDownloadUrl(path: string, absolute?: boolean): string {
  const params = new URLSearchParams({ path });
  if (absolute) params.set("absolute", "true");
  const token = api.getToken();
  if (token) params.set("token", token);
  return `/api/files/download?${params.toString()}`;
}

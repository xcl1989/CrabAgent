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

export async function getTree(path: string = "", depth: number = 5): Promise<FileEntry[]> {
  const params = new URLSearchParams();
  if (path) params.set("path", path);
  params.set("depth", String(depth));
  return api.get<FileEntry[]>(`/files/tree?${params}`);
}

export async function readFile(path: string): Promise<FileContent> {
  return api.get<FileContent>(`/files/read?path=${encodeURIComponent(path)}`);
}

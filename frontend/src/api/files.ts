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

export async function readFile(path: string, absolute: boolean = false): Promise<FileContent> {
  const params = new URLSearchParams();
  params.set("path", path);
  if (absolute) params.set("absolute", "true");
  return api.get<FileContent>(`/files/read?${params}`);
}

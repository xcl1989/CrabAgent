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

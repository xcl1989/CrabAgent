import { defaultUrlTransform } from "react-markdown";
import { getImageUrl } from "../../api/files";

export function markdownImageUrl(raw: string): string {
  // Never attach our token to remote URLs or arbitrary URI schemes.
  if (/^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(raw)) return defaultUrlTransform(raw);
  if (!raw || raw.startsWith("#") || raw.startsWith("/api/")) return defaultUrlTransform(raw);
  let path: string;
  try { path = decodeURIComponent(raw); } catch { return ""; }
  if (/[\\\x00-\x1f]/.test(path) || path.startsWith("//") || path.includes(":")) return "";
  const absolute = path.startsWith("/");
  const parts: string[] = [];
  for (const part of path.split("/")) {
    if (!part || part === ".") continue;
    if (part === "..") {
      if (!parts.length) return "";
      parts.pop();
    } else parts.push(part);
  }
  if (!parts.length) return "";
  return getImageUrl((absolute ? "/" : "") + parts.join("/"), absolute);
}

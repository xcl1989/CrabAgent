export function formatTime(isoStr: string | null | undefined): string {
  if (!isoStr) return "";
  const normalized = isoStr.includes("Z") || isoStr.includes("+") || /-\d{2}:\d{2}$/.test(isoStr)
    ? isoStr : isoStr + "Z";
  return new Date(normalized).toLocaleString();
}

export function formatDate(isoStr: string | null | undefined): string {
  if (!isoStr) return "";
  const normalized = isoStr.includes("Z") || isoStr.includes("+") || /-\d{2}:\d{2}$/.test(isoStr)
    ? isoStr : isoStr + "Z";
  return new Date(normalized).toLocaleDateString();
}

export function formatTimeShort(isoStr: string | null | undefined): string {
  if (!isoStr) return "";
  const normalized = isoStr.includes("Z") || isoStr.includes("+") || /-\d{2}:\d{2}$/.test(isoStr)
    ? isoStr : isoStr + "Z";
  return new Date(normalized).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

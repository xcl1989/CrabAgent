export function formatTime(isoStr: string | null | undefined): string {
  if (!isoStr) return "";
  const hasTz = isoStr.includes("Z") || isoStr.includes("+") || /-\d{2}:\d{2}$/.test(isoStr);
  return new Date(hasTz ? isoStr : isoStr).toLocaleString();
}

export function formatDate(isoStr: string | null | undefined): string {
  if (!isoStr) return "";
  const hasTz = isoStr.includes("Z") || isoStr.includes("+") || /-\d{2}:\d{2}$/.test(isoStr);
  return new Date(hasTz ? isoStr : isoStr).toLocaleDateString();
}

export function formatTimeShort(isoStr: string | null | undefined): string {
  if (!isoStr) return "";
  const hasTz = isoStr.includes("Z") || isoStr.includes("+") || /-\d{2}:\d{2}$/.test(isoStr);
  const d = new Date(hasTz ? isoStr : isoStr);
  const now = new Date();
  const diffDays = (now.getTime() - d.getTime()) / 86400000;
  if (diffDays < 1 && d.getDate() === now.getDate()) {
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } else if (diffDays < 2) {
    return "昨天 " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString([], { month: "2-digit", day: "2-digit" }) + " " +
         d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

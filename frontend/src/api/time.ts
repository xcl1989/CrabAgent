export function formatTime(isoStr: string | null | undefined): string {
  if (!isoStr) return "";
  const hasTz = isoStr.includes("Z") || isoStr.includes("+") || /-\d{2}:\d{2}$/.test(isoStr);
  return new Date(hasTz ? isoStr : isoStr + "Z").toLocaleString();
}

export function formatDate(isoStr: string | null | undefined): string {
  if (!isoStr) return "";
  const hasTz = isoStr.includes("Z") || isoStr.includes("+") || /-\d{2}:\d{2}$/.test(isoStr);
  return new Date(hasTz ? isoStr : isoStr + "Z").toLocaleDateString();
}

export function formatTimeShort(isoStr: string | null | undefined): string {
  if (!isoStr) return "";
  // If the timestamp has timezone info, parse as-is. Otherwise treat as local time.
  const hasTz = isoStr.includes("Z") || isoStr.includes("+") || /-\d{2}:\d{2}$/.test(isoStr);
  const d = hasTz ? new Date(isoStr) : new Date(isoStr + "Z");
  const now = new Date();
  const diffDays = (now.getTime() - d.getTime()) / 86400000;
  if (diffDays < 1 && d.getDate() === now.getDate()) {
    // Today: show time only
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } else if (diffDays < 2) {
    // Yesterday
    return "昨天 " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } else {
    // Older: show date + time
    return d.toLocaleDateString([], { month: "2-digit", day: "2-digit" }) + " " +
           d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
}

import { useEffect, useState } from "react";
import { api } from "../api/client";

interface ActivityRow {
  id: number;
  session: string;
  branch: string;
  scope: string;
  summary: string;
  diff?: string;
}
interface Activity { intentions: ActivityRow[]; changes: ActivityRow[] }

export function FileCollaboration({ sessionId, path, enabled, branch }: {
  sessionId?: string; path?: string | null; enabled?: boolean; branch?: string;
}) {
  const [activity, setActivity] = useState<{ key: string; data: Activity }>();
  const [details, setDetails] = useState<{ key: string; data: Activity }>();
  const key = sessionId && enabled && path ? JSON.stringify([sessionId, branch, path]) : "";
  const endpoint = `/collaboration/sessions/${encodeURIComponent(sessionId ?? "")}/file-activity`;
  useEffect(() => {
    if (!key || !path) return;
    setDetails(undefined);
    let active = true;
    let pending = false;
    const refresh = async () => {
      if (pending) return;
      pending = true;
      try {
        const data = await api.get<Activity>(endpoint, { path });
        if (active) setActivity({ key, data });
      } catch { /* Collaboration hints must not interrupt editing. */ }
      finally { pending = false; }
    };
    void refresh();
    window.addEventListener("focus", refresh);
    window.addEventListener("project-collaboration-update", refresh);
    return () => {
      active = false;
      window.removeEventListener("focus", refresh);
      window.removeEventListener("project-collaboration-update", refresh);
    };
  }, [key, endpoint, path]);
  if (!key || activity?.key !== key || !path) return null;
  const { intentions, changes } = activity.data;
  if (!intentions.length && !changes.length) return null;
  return <aside className="border-b border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2 text-xs space-y-1">
    {intentions.length > 0 && <p className="font-medium">正在协作 · 可继续编辑</p>}
    {intentions.map(row => <p key={row.id}>{row.session.slice(0, 8)}/{row.branch} · {row.scope}：{row.summary}</p>)}
    {changes.length > 0 && <p className="font-medium">其他会话已保存的变更</p>}
    {changes.map(row => <p key={row.id}>{row.session.slice(0, 8)}/{row.branch}：{row.summary}</p>)}
    {changes.length > 0 && <details key={key} onToggle={(event) => {
      if (!event.currentTarget.open) return;
      api.get<Activity>(endpoint, { path, include_diff: "true" })
        .then(data => setDetails({ key, data })).catch(() => {});
    }}>
      <summary className="cursor-pointer">查看已保存的差异</summary>
      {details?.key === key && details.data.changes.map(row => <pre key={row.id} className="max-h-40 overflow-auto whitespace-pre-wrap">{row.diff || row.summary}</pre>)}
    </details>}
  </aside>;
}

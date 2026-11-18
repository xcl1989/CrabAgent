import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { api } from "../api/client";

interface Project { id: number; name: string; workspace: string }
interface Entry { id: number; session_id: string; branch_id: string; kind: string; scope: string; content: string; state: string; created_at: string }

export default function CollaborationPage({ sessionId, onBindingChange }: { sessionId: string | null; onBindingChange?: (enabled: boolean) => void }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [name, setName] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [scope, setScope] = useState("");
  const [content, setContent] = useState("");
  const [error, setError] = useState("");
  const lastSeen = useRef<number | null>(null);
  const loadProjects = async () => setProjects(await api.get<Project[]>("/collaboration/projects"));
  const loadEntries = async (id: number) => setEntries(await api.get<Entry[]>(`/collaboration/projects/${id}/entries`));
  useEffect(() => { loadProjects().catch((e) => setError(String(e))); }, []);
  useEffect(() => {
    if (selected === null) return;
    let active = true;
    lastSeen.current = null;
    const refresh = async () => {
      try {
        const data = await api.get<Entry[]>(`/collaboration/projects/${selected}/entries`);
        if (!active) return;
        const latest = data[0]?.id ?? 0;
        if (lastSeen.current !== null && data.some((entry) => entry.id > lastSeen.current! && entry.session_id !== sessionId)) {
          toast.info("项目有新的协作记录或文件变更");
        }
        lastSeen.current = Math.max(lastSeen.current ?? 0, latest);
        setEntries(data);
      } catch (e) { if (active) setError(String(e)); }
    };
    refresh();
    const timer = setInterval(refresh, 10000);
    return () => { active = false; clearInterval(timer); };
  }, [selected, sessionId]);
  const perform = async (action: () => Promise<void>) => {
    try { setError(""); await action(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  return <div className="h-full overflow-auto p-6 text-[var(--text-primary)]">
    <div className="max-w-5xl mx-auto space-y-5">
      <header><h1 className="text-2xl font-semibold">项目协作</h1><p className="text-sm text-[var(--text-secondary)] mt-1">认领是非排他的编辑意向。同一个文件可以并行编辑，保存时检查版本。</p></header>
      {error && <div role="alert" className="rounded-lg bg-red-500/10 text-red-500 p-3">{error}</div>}
      <section className="flex flex-wrap gap-2 items-center">
        <input aria-label="项目名称" placeholder="项目名称" value={name} onChange={(e) => setName(e.target.value)} className="rounded border p-2 bg-transparent" />
        <input aria-label="工作区路径" placeholder="工作区绝对路径" value={workspace} onChange={(e) => setWorkspace(e.target.value)} className="rounded border p-2 bg-transparent min-w-64" />
        <button className="rounded bg-[var(--brand)] text-white px-4 py-2" onClick={() => perform(async () => { const p = await api.post<Project>("/collaboration/projects", { name, workspace }); await loadProjects(); setSelected(p.id); })}>创建项目</button>
      </section>
      <section className="flex gap-2 flex-wrap">{projects.map((p) => <button key={p.id} onClick={() => setSelected(p.id)} className={`rounded border px-3 py-2 ${selected === p.id ? "border-[var(--brand)]" : "border-[var(--border)]"}`}>{p.name}</button>)}</section>
      {selected !== null && <>
        <div className="text-sm text-[var(--text-secondary)]">{projects.find((p) => p.id === selected)?.workspace}</div>
        <button disabled={!sessionId} className="rounded border px-3 py-2 disabled:opacity-50" onClick={() => perform(async () => { await api.post(`/collaboration/projects/${selected}/bind`, { session_id: sessionId }); onBindingChange?.(true); })}>绑定当前对话{!sessionId && "（请先选择对话）"}</button>
        <button disabled={!sessionId} className="ml-2 rounded border px-3 py-2 disabled:opacity-50" onClick={() => perform(async () => { await api.post(`/collaboration/projects/${selected}/unbind`, { session_id: sessionId }); onBindingChange?.(false); })}>解除当前对话绑定</button>
        <section className="rounded-xl border border-[var(--border)] p-4 space-y-3">
          <h2 className="font-semibold">发布认领或交接</h2>
          <input aria-label="文件或模块范围" placeholder="文件或模块范围（可选）" value={scope} onChange={(e) => setScope(e.target.value)} className="w-full rounded border bg-transparent p-2" />
          <textarea aria-label="协作内容" placeholder="正在处理什么，或交接已完成事项和风险" value={content} onChange={(e) => setContent(e.target.value)} className="w-full rounded border bg-transparent p-2" />
          <div className="flex gap-2">{(["claim", "handoff"] as const).map((kind) => <button key={kind} disabled={!sessionId || !content.trim()} className="rounded border px-3 py-2 disabled:opacity-50" onClick={() => perform(async () => { const result = await api.post<{ overlapping_claims: number[] }>(`/collaboration/projects/${selected}/entries`, { session_id: sessionId, kind, scope, content }); setContent(""); await loadEntries(selected); if (result.overlapping_claims.length) toast.info(`已发布意向；另有 ${result.overlapping_claims.length} 条重叠意向，可继续编辑。`); })}>{kind === "claim" ? "发布认领" : "发布交接"}</button>)}</div>
        </section>
        <section className="space-y-2"><h2 className="font-semibold">协作记录</h2>{entries.map((e) => <article key={e.id} className="rounded-lg border border-[var(--border)] p-3"><div className="text-xs text-[var(--text-secondary)]">{e.kind === "claim" ? "认领" : e.kind === "handoff" ? "交接" : "文件变更"} · {e.session_id} / {e.branch_id} · {e.created_at}</div>{e.scope && <div className="text-sm mt-1">范围：{e.scope}</div>}<p className="whitespace-pre-wrap mt-1">{e.content}</p>{e.kind === "claim" && e.state === "active" && <button className="mt-2 text-sm underline" onClick={() => perform(async () => { await api.post(`/collaboration/projects/${selected}/entries/${e.id}/close`, {}); await loadEntries(selected); })}>结束认领</button>}{e.state === "closed" && <span className="text-xs text-[var(--text-secondary)]">已结束</span>}</article>)}</section>
      </>}
    </div>
  </div>;
}

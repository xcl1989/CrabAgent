import { DeliveryCard, listDeliveries, authorizeDelivery, revokeDelivery } from "../api/backgroundTasks";
import { useEffect, useRef, useState } from "react";
import { BackgroundTask, BackgroundGroup, cancelBackgroundTask, getBackgroundTask, listBackgroundTasks, listBackgroundGroups, getBackgroundGroup, cancelBackgroundGroup, SemanticSummary, getSemanticSummary, startSemanticSummary, cancelSemanticSummary, deleteSemanticSummary, getSummaryProvider, SummaryProvider } from "../api/backgroundTasks";

const labels: Record<string, string> = {
  queued: "排队中", running: "运行中", succeeded: "已完成", failed: "失败",
  cancelled: "已取消", cancelling: "取消中", interrupted: "已中断", skipped: "已跳过", pending: "等待中",
};

export function BackgroundTasks({ sessionId, activeBranch, mobile = false }: { sessionId: string; activeBranch?: string; mobile?: boolean }) {
  const [deliveries, setDeliveries] = useState<DeliveryCard[]>([]);
  const [open, setOpen] = useState(false);
  const [tasks, setTasks] = useState<BackgroundTask[]>([]);
  const [groups, setGroups] = useState<BackgroundGroup[]>([]);
  const [groupDetail, setGroupDetail] = useState<BackgroundGroup | null>(null);
  const [detail, setDetail] = useState<BackgroundTask | null>(null);
  const [semantic, setSemantic] = useState<SemanticSummary | null>(null);
  const [provider, setProvider] = useState<SummaryProvider | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [consentOpen, setConsentOpen] = useState(false);
  const [consent, setConsent] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [deliveryNotice, setDeliveryNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const branch = useRef("");
  const generation = useRef(0);
  const requestSequence = useRef(0);

  useEffect(() => {
    let alive = true;
    generation.current++;
    branch.current = "";
    setDeliveries([]); setTasks([]); setGroups([]); setGroupDetail(null); setDetail(null); setSemantic(null); setDeleteOpen(false); setConsentOpen(false); setPassword(""); setConsent(false); setError(""); setDeliveryNotice(""); setBusy(false);
    const refresh = async () => {
      const sequence = ++requestSequence.current;
      try {
        const [data, groupData, inbox] = await Promise.all([listBackgroundTasks(sessionId), listBackgroundGroups(sessionId), listDeliveries(sessionId)]);
        if (!alive || sequence !== requestSequence.current) return;
        if (inbox.branch !== data.branch || groupData.branch !== data.branch || (activeBranch && data.branch !== activeBranch)) {
          branch.current = ""; generation.current++;
          setDeliveries([]); setTasks([]); setGroups([]); setGroupDetail(null); setDetail(null); setSemantic(null); setDeleteOpen(false); setConsentOpen(false); setPassword(""); setConsent(false); setBusy(false);
          setError("活动分支已变更，正在等待同步。");
          return;
        }
        if (branch.current !== data.branch) {
          branch.current = data.branch;
          generation.current++;
          setDetail(null); setGroupDetail(null); setSemantic(null); setDeleteOpen(false); setConsentOpen(false); setPassword(""); setConsent(false); setBusy(false);
        }
        setTasks(data.tasks); setGroups(groupData.groups); setDeliveries(inbox.deliveries); setError("");
      } catch {
        if (alive && sequence === requestSequence.current) {
          branch.current = ""; generation.current++;
          setDeliveries([]); setTasks([]); setGroups([]); setGroupDetail(null); setDetail(null); setSemantic(null); setDeleteOpen(false); setConsentOpen(false); setPassword(""); setConsent(false); setBusy(false); setError("无法获取后台任务，请稍后重试。");
        }
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => { alive = false; generation.current++; window.clearInterval(timer); };
  }, [sessionId, activeBranch]);

  const action = async (id: string, cancel = false) => {
    const current = generation.current;
    setBusy(true); setError("");
    try {
      const result = cancel
        ? await cancelBackgroundTask(sessionId, branch.current, id)
        : await getBackgroundTask(sessionId, branch.current, id);
      if (current !== generation.current) return;
      requestSequence.current++;
      setDetail(result);
      setTasks((items) => items.map((item) => item.id === id ? result : item));
    } catch {
      if (current === generation.current) { setDetail(null); setError("操作失败，任务可能已变更或会话分支已切换。"); }
    } finally {
      if (current === generation.current) setBusy(false);
    }
  };

  const groupAction = async (id: string, cancel = false) => {
    const current = generation.current;
    setBusy(true); setError("");
    try {
      const result = cancel
        ? await cancelBackgroundGroup(sessionId, branch.current, id)
        : await getBackgroundGroup(sessionId, branch.current, id);
      if (current !== generation.current) return;
      requestSequence.current++;
      setGroupDetail(result);
      setSemantic(null); setDeleteOpen(false); setConsentOpen(false); setPassword(""); setConsent(false);
      const summary = await getSemanticSummary(sessionId, branch.current, id);
      if (current !== generation.current) return;
      setSemantic(summary.summary);
      setGroups((items) => items.map((item) => item.id === id ? result : item));
    } catch {
      if (current === generation.current) { setGroupDetail(null); setError("操作失败，任务组可能已变更或会话分支已切换。"); }
    } finally {
      if (current === generation.current) setBusy(false);
    }
  };

  const summaryAction = async (operation: "refresh" | "start" | "cancel") => {
    if (!groupDetail) return;
    const current = generation.current;
    setBusy(true); setError("");
    try {
      const result = operation === "start" ? await startSemanticSummary(sessionId, branch.current, groupDetail.id, password, provider?.binding ?? "")
        : operation === "cancel" ? await cancelSemanticSummary(sessionId, branch.current, groupDetail.id)
        : await getSemanticSummary(sessionId, branch.current, groupDetail.id);
      if (current !== generation.current) return;
      setSemantic(result.summary); setConsentOpen(false); setPassword(""); setConsent(false);
    } catch {
      if (current === generation.current) { setPassword(""); setError("语义汇总操作失败，请检查密码、任务状态或稍后重试。"); }
    } finally { if (current === generation.current) setBusy(false); }
  };

  const deleteSummary = async () => {
    if (!groupDetail) return;
    const current = generation.current;
    setBusy(true); setError("");
    try {
      await deleteSemanticSummary(sessionId, branch.current, groupDetail.id);
      if (current === generation.current) { setSemantic(null); setDeleteOpen(false); }
    } catch {
      if (current === generation.current) setError("清理失败，摘要可能仍在运行或会话分支已切换。");
    } finally { if (current === generation.current) setBusy(false); }
  };

  const openConsent = async () => {
    if (!groupDetail) return;
    const current = generation.current;
    setBusy(true); setError(""); setProvider(null); setConsent(false); setPassword("");
    try {
      const identity = await getSummaryProvider(sessionId, branch.current, groupDetail.id);
      if (current === generation.current) { setProvider(identity); setConsentOpen(true); }
    } catch {
      if (current === generation.current) setError("无法获取当前供应商信息，请稍后重试。");
    } finally { if (current === generation.current) setBusy(false); }
  };

  const deliveryAction = async (id: string, authorize: boolean) => {
    if (authorize && !window.confirm("授权此任务组结束后自动展示独立结果卡？结果未经验证，不会加入模型消息；可随时撤销。")) return;
    const current = generation.current;
    setBusy(true); setError(""); setDeliveryNotice("");
    try {
      if (authorize) await authorizeDelivery(sessionId, branch.current, id);
      else await revokeDelivery(sessionId, branch.current, id);
      if (current !== generation.current) return;
      requestSequence.current++;
      if (!authorize) setDeliveries(items => items.filter(item => item.id !== id));
      setDeliveryNotice(authorize ? "已授权此任务组结束后展示结果卡。" : "已撤销展示授权。");
    } catch {
      if (current === generation.current) setError(authorize ? "授权失败，任务可能已结束或已授权。" : "撤销失败，请重试。");
    } finally {
      if (current === generation.current) setBusy(false);
    }
  };

  if (tasks.length === 0 && groups.length === 0 && deliveries.length === 0 && !error && !deliveryNotice) return null;

  return <section className={mobile ? "border-b border-zinc-800 bg-zinc-950 px-4 py-1 text-sm text-zinc-100" : "border-b border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-1 text-sm"}>
    <div className="flex justify-end">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className={mobile ? "rounded px-2 py-1 text-xs text-zinc-400 hover:text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2" : "rounded px-2 py-1 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"}>
        后台子任务 ({tasks.length}) · 任务组 ({groups.length}) {open ? "▴" : "▾"}
      </button>
    </div>
    {error && <p role="alert" className="text-red-500">{error}</p>}
    {deliveryNotice && <p role="status">{deliveryNotice}</p>}
    {deliveries.map((card) => <article key={card.id} className="my-2 rounded border border-[var(--border)] p-3" aria-label="后台结果卡">
      <strong>后台结果 · {card.id} · {labels[card.status] ?? card.status}</strong>
      <p>独立展示的未验证数据，不会发送给模型。</p>
      {card.steps.map((step) => <div key={step.step_id}><p>{step.step_id} · {labels[step.status] ?? step.status}</p><pre className="whitespace-pre-wrap break-words font-sans">{step.result}</pre></div>)}
      <button className="underline" disabled={busy} onClick={() => void deliveryAction(card.id, false)}>撤销展示授权</button>
    </article>)}
    {open && <div className="mt-2 max-h-72 overflow-auto space-y-2">
      <p className={mobile ? "text-xs text-zinc-400" : "text-xs text-[var(--text-tertiary)]"}>仅显示当前会话活动分支；结果不会自动合并到对话。</p>
      {!error && tasks.length === 0 && groups.length === 0 && <p>暂无后台任务</p>}
      {groups.map((group) => <div key={group.id} className={mobile ? "rounded border border-zinc-700 p-2" : "rounded border border-[var(--border)] p-2"}>
        <div className="flex flex-wrap items-center gap-2">
          <strong>任务组 {group.id}</strong><span>{labels[group.status] ?? group.status}</span>
          <button disabled={busy} onClick={() => void groupAction(group.id)} className="underline">查看详情</button>
          {(group.status === "queued" || group.status === "running") && <button disabled={busy} className="underline" onClick={() => void deliveryAction(group.id, true)}>授权自动展示</button>}
          <button disabled={busy} className="underline" onClick={() => void deliveryAction(group.id, false)}>撤销展示授权</button>
          {(group.status === "queued" || group.status === "running") && <button disabled={busy} onClick={() => void groupAction(group.id, true)} className="underline">取消任务组</button>}
        </div>
        {groupDetail?.id === group.id && <div className="mt-2 space-y-2">
          {groupDetail.steps?.map((step) => <div key={step.step_id} className="break-words">
            <p><strong>{step.step_id}</strong> · {step.agent_name} · {labels[step.status] ?? step.status}</p>
            <p>{step.task}</p><p>依赖：{step.depends_on.join(", ") || "无"}</p>
            <p>子任务输出（未经验证）</p><pre className="whitespace-pre-wrap break-words font-sans">{step.result || "暂无结果"}</pre>
          </div>)}
          <div className="border-t border-current pt-2 space-y-2">
            <p>语义汇总（模型生成，未经验证）{semantic && ` · ${labels[semantic.status] ?? semantic.status}`}</p>
            {semantic && <pre className="whitespace-pre-wrap break-words font-sans">{semantic.text || "暂无结果"}</pre>}
            <button disabled={busy} onClick={() => void summaryAction("refresh")} className="underline">刷新语义汇总状态</button>{" "}
            {semantic && ["pending", "running", "cancelling"].includes(semantic.status) && <button disabled={busy} onClick={() => void summaryAction("cancel")} className="underline">取消语义汇总</button>}
            {semantic && ["succeeded", "failed", "interrupted", "cancelled"].includes(semantic.status) && !deleteOpen && <button disabled={busy} onClick={() => setDeleteOpen(true)} className="underline">清理本地语义汇总</button>}
            {deleteOpen && <div className="space-y-2">
              <p>确认删除本地语义汇总及其步骤快照？此操作不可撤销，不会删除原任务结果、数据库备份或供应商保存的数据，也不保证从存储介质彻底擦除。</p>
              <button disabled={busy} onClick={() => void deleteSummary()} className="underline">确认清理</button>{" "}
              <button disabled={busy} onClick={() => setDeleteOpen(false)} className="underline">取消清理</button>
            </div>}
            {(!semantic || ["failed", "interrupted", "cancelled"].includes(semantic.status)) && ["succeeded", "failed"].includes(group.status) && !consentOpen && <button disabled={busy} onClick={() => void openConsent()} className="underline">申请语义汇总</button>}
            {consentOpen && <div className="space-y-2">
              <p>将发送此任务组所有步骤的状态和结果至本会话配置的模型供应商，可能包含敏感信息；供应商可能保存或处理这些数据。步骤结果快照和汇总文本将额外以明文保存在本地数据库，目前没有自动过期机制，可在汇总结束后手动清理。取消不保证远端停止。请先检查步骤结果。</p>
              <p>供应商：{provider?.name}（{provider?.type}）；模型：{provider?.model}；端点：{provider?.endpoint}；当前代理：{provider?.proxy}</p>
              <p>摘要请求与你日常对话使用完全相同的供应商、模型和网络路径（代理跟随全局配置）；供应商或模型配置变化后需重新确认。</p>
              <label><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} /> 我明确同意发送上述数据以生成语义汇总</label>
              <label className="block">输入账户密码以确认 <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className="text-black" /></label>
              <button disabled={busy || !consent || !password || !provider} onClick={() => void summaryAction("start")} className="underline">确认发送并生成</button>{" "}
              <button onClick={() => { setConsentOpen(false); setPassword(""); setConsent(false); }} className="underline">返回</button>
            </div>}
          </div>
          {groupDetail.summary && <div><p>汇总（未经验证） · {labels[groupDetail.summary.status] ?? groupDetail.summary.status}</p><pre className="whitespace-pre-wrap break-words font-sans">{groupDetail.summary.text || "暂无结果"}</pre></div>}
        </div>}
      </div>)}
      {tasks.map((task) => <div key={task.id} className={mobile ? "rounded border border-zinc-700 p-2" : "rounded border border-[var(--border)] p-2"}>
        <div className="flex flex-wrap items-center gap-2">
          <strong>{task.agent_name}</strong><span>{labels[task.status] ?? task.status}</span>
          <button disabled={busy} onClick={() => void action(task.id)} className="underline">查看结果</button>
          {(task.status === "queued" || task.status === "running") && <button disabled={busy} onClick={() => void action(task.id, true)} className="underline">取消任务</button>}
        </div>
        <p className={mobile ? "break-words text-zinc-300" : "break-words text-[var(--text-secondary)]"}>{task.task}</p>
        {detail?.id === task.id && <div className="mt-2"><p className={mobile ? "text-xs text-zinc-400" : "text-xs text-[var(--text-tertiary)]"}>子任务输出（未经验证）</p><pre className="whitespace-pre-wrap break-words font-sans">{detail.result || "暂无结果"}</pre></div>}
      </div>)}
    </div>}
  </section>;
}

import { useEffect, useState } from "react";
import { ArrowLeft, FileText, FolderOpen, Loader2, Search, Sparkles } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Modal } from "./ui";
import * as settingsApi from "../api/settings";
import type { SkillInfo, SkillDetail } from "../api/settings";
import { cn } from "../lib/cn";

interface Props { onClose: () => void }
type Status = "loading" | "ready" | "error";
const buttonStyle = "rounded-md px-3 py-1.5 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]";

export default function SkillsPanel({ onClose }: Props) {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [listStatus, setListStatus] = useState<Status>("loading");
  const [listAttempt, setListAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [detailStatus, setDetailStatus] = useState<Status>("loading");
  const [detailAttempt, setDetailAttempt] = useState(0);
  const [view, setView] = useState<"markdown" | "raw">("markdown");

  useEffect(() => {
    let active = true;
    setListStatus("loading");
    settingsApi.getSkills().then((items) => {
      if (active) { setSkills(items); setListStatus("ready"); }
    }).catch(() => { if (active) setListStatus("error"); });
    return () => { active = false; };
  }, [listAttempt]);

  useEffect(() => {
    if (!selected) return;
    let active = true;
    setDetail(null);
    setDetailStatus("loading");
    settingsApi.getSkillDetail(selected).then((item) => {
      if (active) { setDetail(item); setDetailStatus("ready"); }
    }).catch(() => { if (active) setDetailStatus("error"); });
    return () => { active = false; };
  }, [selected, detailAttempt]);

  const filtered = skills.filter((skill) => `${skill.name} ${skill.description}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  return (
    <Modal open onOpenChange={(open) => !open && onClose()} size="full" title={<span className="flex items-center gap-2"><Sparkles size={16} className="text-[var(--brand)]" />Skills</span>}>
      <div className="md:flex md:gap-5 md:h-[65vh] min-h-[45vh]">
        <section aria-label="Skills list" className={cn("md:w-1/3 md:shrink-0 md:flex md:flex-col md:border-r md:border-[var(--border)] md:pr-4", selected && "hidden")}>
          <div className="relative mb-3">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]" aria-hidden="true" />
            <input aria-label="Search skills" placeholder="Search skills..." value={query} onChange={(event) => setQuery(event.target.value)} className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] py-2 pl-9 pr-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]" />
          </div>
          <div className="md:overflow-y-auto space-y-2">
            {listStatus === "loading" ? <p role="status" className="text-sm text-[var(--text-secondary)]">Loading skills...</p> : listStatus === "error" ? <div role="alert" className="text-sm text-[var(--danger)]">Failed to load skills. <button className={buttonStyle} onClick={() => setListAttempt((n) => n + 1)}>Retry</button></div> : skills.length === 0 ? <p className="text-sm text-[var(--text-secondary)]">No skills loaded. Place SKILL.md in ~/.crabagent/skills/.</p> : filtered.length === 0 ? <p className="text-sm text-[var(--text-secondary)]">No matching skills.</p> : filtered.map((skill) => <button key={skill.name} type="button" aria-pressed={selected === skill.name} onClick={() => { setSelected(skill.name); setView("markdown"); }} className={cn("w-full rounded-lg border p-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]", selected === skill.name ? "border-[var(--brand)] bg-[var(--brand-bg)]" : "border-[var(--border)] bg-[var(--bg-tertiary)]/30")}><span className="block text-sm font-medium text-[var(--text-primary)]">{skill.name}</span><span className="mt-1 block text-xs text-[var(--text-tertiary)] line-clamp-2">{skill.description}</span><span className="mt-1 block text-xs text-[var(--text-tertiary)]">{skill.auxiliary_files.length} auxiliary files</span></button>)}
          </div>
        </section>
        <section aria-label="Skill detail" className={cn("min-w-0 flex-1 md:block md:overflow-y-auto", !selected && "hidden")}>
          {!selected ? <p className="text-sm text-[var(--text-secondary)]">Select a skill to view its details.</p> : <>
            <button type="button" onClick={() => setSelected(null)} className={cn(buttonStyle, "mb-3 inline-flex items-center gap-1 text-[var(--text-secondary)] md:hidden")}><ArrowLeft size={14} /> Back to skills</button>
            <h2 className="mb-3 text-base font-semibold text-[var(--text-primary)]">{selected}</h2>
            {detailStatus === "loading" ? <p role="status" className="flex items-center gap-2 text-sm text-[var(--text-secondary)]"><Loader2 size={14} className="animate-spin" />Loading skill...</p> : detailStatus === "error" ? <div role="alert" className="text-sm text-[var(--danger)]">Failed to load skill detail. <button className={buttonStyle} onClick={() => setDetailAttempt((n) => n + 1)}>Retry</button></div> : detail && <>
              <p className="mb-3 flex items-center gap-1.5 break-all text-xs text-[var(--text-tertiary)]"><FolderOpen size={13} className="shrink-0" />{detail.location}</p>
              <div role="group" aria-label="Content view" className="mb-3 flex gap-1"><button type="button" aria-pressed={view === "markdown"} onClick={() => setView("markdown")} className={cn(buttonStyle, view === "markdown" && "bg-[var(--brand-bg)] text-[var(--brand)]")}>Markdown</button><button type="button" aria-pressed={view === "raw"} onClick={() => setView("raw")} className={cn(buttonStyle, view === "raw" && "bg-[var(--brand-bg)] text-[var(--brand)]")}>Raw</button></div>
              {view === "raw" ? <pre className="whitespace-pre-wrap break-words rounded-md border border-[var(--border)] bg-[var(--bg-primary)] p-3 text-xs text-[var(--text-secondary)]">{detail.content}</pre> : <div className="markdown-body overflow-x-auto rounded-md border border-[var(--border)] bg-[var(--bg-primary)] p-3 text-sm text-[var(--text-primary)]"><ReactMarkdown remarkPlugins={[remarkGfm]}>{detail.content}</ReactMarkdown></div>}
              <h3 className="mt-4 mb-2 text-xs font-semibold uppercase text-[var(--text-tertiary)]">Auxiliary files</h3>
              {detail.auxiliary_files.length ? <ul className="space-y-1">{detail.auxiliary_files.map((file) => <li key={file} className="flex items-center gap-2 break-all text-xs text-[var(--text-secondary)]"><FileText size={12} className="shrink-0" />{file}</li>)}</ul> : <p className="text-xs text-[var(--text-tertiary)]">No auxiliary files.</p>}
            </>}
          </>}
        </section>
      </div>
    </Modal>
  );
}

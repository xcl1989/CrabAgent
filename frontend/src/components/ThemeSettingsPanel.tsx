import { useState } from "react";
import { DEFAULT_COLORS, useTheme, validImage, type CustomTheme, type ColorKey, type Theme, type ThemeMode } from "../lib/theme";

const inputClass = "w-full rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-sm text-[var(--text-primary)]";
const buttonClass = "rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:border-[var(--brand)]";
export default function ThemeSettingsPanel() {
  const { theme, mode, setMode, themes, activeId, selectTheme, saveTheme, deleteTheme, imageError } = useTheme();
  const [draft, setDraft] = useState<CustomTheme | null>(null);
  const [editingMode, setEditingMode] = useState<Theme>(theme);
  const [imageFile, setImageFile] = useState<File | undefined>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const create = () => { setImageFile(undefined); setError(""); setDraft({ id: crypto.randomUUID(), name: "新主题", colors: { light: { ...DEFAULT_COLORS.light }, dark: { ...DEFAULT_COLORS.dark } }, backgroundImage: "" }); };
  const groups: [string, [ColorKey, string][]][] = [
    ["背景与面板", [["bg-primary", "主背景"], ["bg-secondary", "面板"], ["bg-tertiary", "次级背景"], ["bg-elevated", "浮层"]]],
    ["文字与边框", [["text-primary", "主要文字"], ["text-secondary", "次要文字"], ["text-tertiary", "辅助文字"], ["text-on-brand", "品牌上文字"], ["text-on-accent", "强调上文字"], ["border", "边框"], ["border-subtle", "弱边框"], ["border-strong", "强边框"]]],
    ["品牌与强调", [["brand", "品牌"], ["brand-hover", "品牌悬停"], ["brand-active", "品牌按下"], ["accent", "强调"], ["accent-hover", "强调悬停"], ["accent-2", "次强调"], ["accent-2-hover", "次强调悬停"]]],
    ["状态与代码", [["success", "成功"], ["warning", "警告"], ["danger", "危险"], ["danger-hover", "危险悬停"], ["code-bg", "代码背景"], ["code-border", "代码边框"]]],
    ["智能体与图表", [["agent-researcher", "研究"], ["agent-analyst", "分析"], ["agent-coder", "代码"], ["agent-writer", "写作"], ["agent-plan_creater", "计划"]]],
  ];
  const safely = (action: () => void) => { try { action(); setError(""); } catch { setError("保存失败，请检查数据或浏览器存储空间。"); } };
  return <div className="space-y-4">
    <section className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-5 space-y-3">
      <h2 className="font-semibold">外观模式</h2>
      <p className="text-xs text-[var(--text-secondary)]">跟随系统时，外观会随系统设置自动切换。</p>
      <div className="flex flex-wrap gap-2">{([ ["light", "浅色"], ["dark", "深色"], ["system", "跟随系统"] ] as [ThemeMode, string][]).map(([value, label]) => <button key={value} className={buttonClass} aria-pressed={mode === value} style={mode === value ? { borderColor: "var(--brand)", color: "var(--brand)" } : undefined} onClick={() => safely(() => setMode(value))}>{label}</button>)}</div>
    </section>
    <section className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-5 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><div><h2 className="font-semibold">主题管理</h2><p className="text-xs text-[var(--text-secondary)]">主题保存在当前浏览器中，颜色和图片覆盖当前外观。</p></div><button className={buttonClass} onClick={create}>创建主题</button></div>
      <div className="flex flex-wrap gap-2"><button className={buttonClass} aria-pressed={!activeId} onClick={() => safely(() => selectTheme(""))}>默认主题{!activeId ? " ✓" : ""}</button>{themes.map(item => <div key={item.id} className="flex items-center gap-1 rounded-lg border border-[var(--border)] p-1"><button className="px-2 py-1 text-sm" aria-pressed={activeId === item.id} onClick={() => safely(() => selectTheme(item.id))}>{item.name}{activeId === item.id ? " ✓" : ""}</button><button className="px-2 py-1 text-xs" onClick={() => { setImageFile(undefined); setDraft({ ...item, colors: { light: { ...item.colors.light }, dark: { ...item.colors.dark } } }); setError(""); }}>编辑</button><button className="px-2 py-1 text-xs text-[var(--danger)]" disabled={busy} onClick={async () => { setBusy(true); try { await deleteTheme(item.id); if (draft?.id === item.id) setDraft(null); setError(""); } catch { setError("删除失败，请检查浏览器存储。"); } finally { setBusy(false); } }}>删除</button></div>)}</div>
      {draft && <div className="space-y-4 border-t border-[var(--border)] pt-4"><label className="block text-sm">主题名称<input className={`${inputClass} mt-1`} maxLength={40} value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} /></label><div className="flex gap-2">{([ ["light", "编辑浅色配色"], ["dark", "编辑深色配色"] ] as [Theme, string][]).map(([value, label]) => <button key={value} className={buttonClass} aria-pressed={editingMode === value} style={editingMode === value ? { borderColor: "var(--brand)", color: "var(--brand)" } : undefined} onClick={() => setEditingMode(value)}>{label}</button>)}</div>{groups.map(([group, fields]) => <fieldset key={group}><legend className="mb-2 text-sm font-semibold">{group}</legend><div className="grid grid-cols-2 gap-3 sm:grid-cols-4">{fields.map(([key, label]) => <label key={key} className="text-sm">{label}<input className="mt-1 block h-10 w-full cursor-pointer rounded border border-[var(--border)] bg-transparent" type="color" value={draft.colors[editingMode][key]} onChange={e => setDraft({ ...draft, colors: { ...draft.colors, [editingMode]: { ...draft.colors[editingMode], [key]: e.target.value } } })} /></label>)}</div></fieldset>)}
        <label className="block text-sm">背景图片网址<input className={`${inputClass} mt-1`} placeholder="https://..." value={draft.backgroundImage.startsWith("data:") || draft.backgroundImage.startsWith("indexeddb:") ? "" : draft.backgroundImage} onChange={e => { setImageFile(undefined); setDraft({ ...draft, backgroundImage: e.target.value }); }} /></label><label className="block text-sm">或上传图片（最大 10 MB）<input className="mt-1 block w-full text-xs" type="file" accept="image/png,image/jpeg,image/gif,image/webp" onChange={e => { const file = e.target.files?.[0]; if (!file) return; if (file.size > 10 * 1024 * 1024 || !["image/png", "image/jpeg", "image/gif", "image/webp"].includes(file.type)) { setError("请选择不超过 10 MB 的 PNG、JPEG、GIF 或 WebP 图片。"); e.target.value = ""; return; } setImageFile(file); setError(""); }} /></label>{(draft.backgroundImage || imageFile) && <button className={buttonClass} onClick={() => { setImageFile(undefined); setDraft({ ...draft, backgroundImage: "" }); }}>移除背景图片</button>}
        <div className="flex gap-2"><button className={buttonClass} disabled={busy} onClick={async () => { if (!draft.name.trim() || !validImage(draft.backgroundImage)) { setError("请输入名称及有效的 HTTP(S) 图片网址。"); return; } setBusy(true); try { await saveTheme({ ...draft, name: draft.name.trim() }, imageFile); setDraft(null); setImageFile(undefined); setError(""); } catch { setError("保存失败，请检查浏览器存储空间或权限。"); } finally { setBusy(false); } }}>保存并应用</button><button className={buttonClass} disabled={busy} onClick={() => { setDraft(null); setImageFile(undefined); setError(""); }}>取消</button></div></div>}
      {imageError && <p role="alert" className="text-sm text-[var(--danger)]">{imageError}</p>}
      {error && <p role="alert" className="text-sm text-[var(--danger)]">{error}</p>}
    </section>
  </div>;
}

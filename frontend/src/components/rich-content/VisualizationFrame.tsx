import { useState, type ReactNode } from "react";
import { Check, Copy, ChevronDown, ChevronUp } from "lucide-react";

export function VisualizationFrame({ title, source, children }: { title: string; source: string; children: ReactNode }) {
  const [showSource, setShowSource] = useState(false);
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(source); setCopied(true); window.setTimeout(() => setCopied(false), 1500); } catch { /* Clipboard can be unavailable. */ }
  };
  return <section className="visualization-frame" aria-label={title}>
    <header className="visualization-frame__header">
      <span>{title}</span>
      <span className="visualization-frame__actions">
        <button onClick={copy} title="复制源数据">{copied ? <Check size={13} /> : <Copy size={13} />}</button>
        <button onClick={() => setShowSource((value) => !value)} title={showSource ? "隐藏源数据" : "查看源数据"}>{showSource ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</button>
      </span>
    </header>
    <div className="visualization-frame__content">{children}</div>
    {showSource && <pre className="visualization-frame__source">{source}</pre>}
  </section>;
}

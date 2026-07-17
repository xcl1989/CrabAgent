import { useEffect, useId, useState } from "react";
import mermaid from "mermaid";
import { AlertTriangle, Loader2 } from "lucide-react";
import { VisualizationFrame } from "./VisualizationFrame";

let initialized = false;
function setupMermaid() {
  if (initialized) return;
  mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "base", themeVariables: { primaryColor: "#ccfbf1", primaryTextColor: "#134e4a", primaryBorderColor: "#0f766e", lineColor: "#64748b", secondaryColor: "#fff7ed", tertiaryColor: "#f8fafc", fontFamily: "Georgia, serif" } });
  initialized = true;
}

export function MermaidDiagram({ source }: { source: string }) {
  const id = useId().replace(/:/g, "-");
  const [state, setState] = useState<{ svg?: string; error?: string }>({});
  useEffect(() => {
    let active = true;
    setupMermaid();
    setState({});
    mermaid.render(`mermaid-${id}`, source).then(({ svg }) => active && setState({ svg })).catch(() => active && setState({ error: "无法解析 Mermaid 图，请检查语法。" }));
    return () => { active = false; };
  }, [id, source]);
  return <VisualizationFrame title="流程图" source={source}>
    {state.svg ? <div className="mermaid-diagram" dangerouslySetInnerHTML={{ __html: state.svg }} /> : state.error ? <div className="visualization-error"><AlertTriangle size={17} /><span>{state.error}</span></div> : <div className="visualization-loading"><Loader2 size={16} className="animate-spin" />正在生成图表…</div>}
  </VisualizationFrame>;
}

/**
 * ToolResultRender — Per-tool-type rendering for expanded tool call details.
 * Replaces the raw JSON Arguments/Result dump with human-readable visualizations.
 */
import { useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Terminal, FileText, Pencil, Search, FolderOpen, Save, Globe,
  GitBranch, Zap, Check, X, AlertTriangle, ChevronDown,
} from "lucide-react";
import { cn } from "../lib/cn";
import i18n from "../i18n";

// Shorthand for i18n in non-component functions
const _t = (key: string, opts?: Record<string, unknown>) => i18n.t(key, opts);

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

interface ToolResultRenderProps {
  name: string;
  argsJson: string;     // raw JSON string of tool call content
  result: string;       // tool result text
  images?: string[];    // optional screenshots
  onPreviewImage?: (url: string) => void;
  accentVar?: string;   // "var(--accent)" or "var(--accent-2)"
}

export default function ToolResultRender({
  name,
  argsJson,
  result,
  images,
  onPreviewImage,
  accentVar = "var(--accent)",
}: ToolResultRenderProps) {
  const args = parseArgs(argsJson);

  // Dispatch to per-tool renderer
  switch (name) {
    case "edit":
      return <EditRender args={args} result={result} accentVar={accentVar} />;
    case "write":
      return <WriteRender args={args} result={result} accentVar={accentVar} />;
    case "read":
      return <ReadRender args={args} result={result} accentVar={accentVar} />;
    case "bash":
      return <BashRender args={args} result={result} accentVar={accentVar} />;
    case "grep":
      return <GrepRender args={args} result={result} accentVar={accentVar} />;
    case "glob":
      return <GlobRender args={args} result={result} accentVar={accentVar} />;
    case "memory_save":
    case "memory_recall":
    case "memory_replace":
    case "memory_list":
    case "memory_forget":
      return <MemoryRender name={name} args={args} result={result} accentVar={accentVar} />;
    case "web_search":
    case "web_scrape":
      return <WebRender name={name} args={args} result={result} accentVar={accentVar} />;
    case "delegate_task":
    case "delegate_parallel":
    case "run_pipeline":
    case "handoff_to":
    case "request_help":
    case "plan_task":
      return <DelegateRender name={name} args={args} result={result} accentVar={accentVar} />;
    case "image_generate":
      return <ImageGenerateRender args={args} result={result} images={images} onPreviewImage={onPreviewImage} accentVar={accentVar} />;
    default:
      return <GenericRender name={name} args={args} result={result} images={images} onPreviewImage={onPreviewImage} accentVar={accentVar} />;
  }
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function parseArgs(raw: string): Record<string, unknown> {
  try {
    const data = JSON.parse(raw);
    return (data.arguments as Record<string, unknown>) || {};
  } catch {
    return {};
  }
}

function Container({ children, accentVar }: { children: ReactNode; accentVar?: string }) {
  return (
    <div
      className="mt-1.5 rounded-lg overflow-hidden bg-[var(--bg-secondary)] border border-[var(--border)] max-h-80 overflow-y-auto"
      style={{ borderLeft: `3px solid ${accentVar || "var(--accent)"}` }}
    >
      {children}
    </div>
  );
}

function Header({ icon, title, subtitle }: { icon: ReactNode; title: string; subtitle?: string }) {
  return (
    <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--border-subtle)]">
      <span className="flex items-center justify-center w-5 h-5 rounded shrink-0"
        style={{ color: "var(--accent)", background: "var(--accent-bg)" }}>
        {icon}
      </span>
      <span className="text-xs font-semibold text-[var(--accent)] truncate">{title}</span>
      {subtitle && (
        <span className="text-[10px] text-[var(--text-tertiary)] truncate font-mono">{subtitle}</span>
      )}
    </div>
  );
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function isError(result: string): boolean {
  const r = result.trim().toLowerCase();
  return r.startsWith("error") || r.startsWith("fail");
}

// Simple diff: old_string lines as removed, new_string lines as added
interface DiffLine {
  type: "add" | "remove";
  text: string;
}

function computeDiff(oldStr: string, newStr: string): { oldLines: DiffLine[]; newLines: DiffLine[] } {
  const oldParts = oldStr.split("\n");
  const newParts = newStr.split("\n");
  return {
    oldLines: oldParts.map((t) => ({ type: "remove" as const, text: t })),
    newLines: newParts.map((t) => ({ type: "add" as const, text: t })),
  };
}

// ---------------------------------------------------------------------------
// 1. Edit — Dual-column diff
// ---------------------------------------------------------------------------

function EditRender({ args, result, accentVar }: { args: Record<string, unknown>; result: string; accentVar: string }) {
  const filePath = str(args.file_path) || str(args.path) || "";
  const oldStr = str(args.old_string) || "";
  const newStr = str(args.new_string) || "";
  const { oldLines, newLines } = computeDiff(oldStr, newStr);
  const hasOld = oldLines.length > 0;
  const err = isError(result);

  // Parse starting line number from result: "… @ L139"
  const lineMatch = result.match(/@ L(\d+)/);
  const startLine = lineMatch ? parseInt(lineMatch[1]) : 0;

  return (
    <Container accentVar={accentVar}>
      <Header icon={<Pencil size={13} />} title={_t("toolResult.edit")} subtitle={filePath} />
      <div className="flex text-[12px] font-mono leading-[1.5]">
        {/* Left: Original */}
        <div className="flex-1 min-w-0 border-r border-[var(--border)]">
          <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)] bg-[var(--bg-tertiary)] border-b border-[var(--border-subtle)] sticky top-0">
            {_t("toolResult.original")}
          </div>
          {hasOld ? oldLines.map((line, i) => (
            <div key={i} className="flex px-1" style={{ background: "var(--danger-bg)" }}>
              <span className="shrink-0 w-8 text-right pr-1 text-[var(--text-tertiary)] select-none">
                {startLine > 0 ? startLine + i : "−"}
              </span>
              <span className="text-[var(--danger)] whitespace-pre-wrap break-all">{line.text}</span>
            </div>
          )) : (
            <div className="px-2 py-4 text-center text-[var(--text-tertiary)] text-[11px]">—</div>
          )}
        </div>
        {/* Right: New */}
        <div className="flex-1 min-w-0">
          <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)] bg-[var(--bg-tertiary)] border-b border-[var(--border-subtle)] sticky top-0">
            {_t("toolResult.new")}
          </div>
          {newLines.map((line, i) => (
            <div key={i} className="flex px-1" style={{ background: "var(--success-bg)" }}>
              <span className="shrink-0 w-8 text-right pr-1 text-[var(--text-tertiary)] select-none">
                {startLine > 0 ? startLine + i : "+"}
              </span>
              <span className="text-[var(--success)] whitespace-pre-wrap break-all">{line.text}</span>
            </div>
          ))}
        </div>
      </div>
      {/* Stats footer */}
      <div className="flex items-center gap-3 px-3 py-1.5 text-[11px] border-t border-[var(--border-subtle)]">
        {hasOld && (
          <span className="flex items-center gap-1 text-[var(--danger)]">
            <X size={11} /> -{oldLines.length} {oldLines.length === 1 ? "line" : "lines"}
          </span>
        )}
        <span className="flex items-center gap-1 text-[var(--success)]">
          <Check size={11} /> +{newLines.length} {newLines.length === 1 ? "line" : "lines"}
        </span>
        {filePath && <span className="text-[var(--text-tertiary)] font-mono truncate">
          in {filePath.split("/").slice(-2).join("/")}{startLine > 0 ? ` @ L${startLine}` : ""}
        </span>}
      </div>
      {err && (
        <div className="px-3 py-1.5 text-[11px] text-[var(--danger)] border-t border-[var(--border-subtle)]">
          {result}
        </div>
      )}
    </Container>
  );
}

// ---------------------------------------------------------------------------
// 2. Write — New file preview
// ---------------------------------------------------------------------------

function WriteRender({ args, result, accentVar }: { args: Record<string, unknown>; result: string; accentVar: string }) {
  const filePath = str(args.file_path) || str(args.path) || "";
  const content = str(args.content) || "";
  const lines = content.split("\n");
  const err = isError(result);

  return (
    <Container accentVar={accentVar}>
      <Header icon={<Pencil size={13} />} title={_t("toolResult.write")} subtitle={`${filePath} · ${_t("toolResult.bytes", { size: formatBytes(content.length) })}`} />
      {err ? (
        <div className="px-3 py-2 text-[12px] text-[var(--danger)]">{result}</div>
      ) : (
        <FileContentLines lines={lines} maxLines={20} />
      )}
    </Container>
  );
}

// ---------------------------------------------------------------------------
// 3. Read — File browser
// ---------------------------------------------------------------------------

function ReadRender({ args, result, accentVar }: { args: Record<string, unknown>; result: string; accentVar: string }) {
  const filePath = str(args.path) || "";
  const err = isError(result);
  const lines = result.split("\n");

  return (
    <Container accentVar={accentVar}>
      <Header icon={<FileText size={13} />} title={_t("toolResult.read")} subtitle={filePath} />
      {err ? (
        <div className="px-3 py-2 text-[12px] text-[var(--danger)]">{result}</div>
      ) : (
        <FileContentLines lines={lines} maxLines={20} />
      )}
    </Container>
  );
}

// Shared: file content with line numbers
function FileContentLines({ lines, maxLines = 20 }: { lines: string[]; maxLines?: number }) {
  const [expanded, setExpanded] = useState(false);
  const shouldCollapse = lines.length > maxLines + 2;
  const visible = shouldCollapse && !expanded ? lines.slice(0, maxLines) : lines;
  const lineNumWidth = String(lines.length).length;

  return (
    <>
      <div className="py-1 bg-[var(--code-bg)]">
        {visible.map((line, i) => (
          <div key={i} className="flex px-1 text-[12px] font-mono leading-[1.5]">
            <span
              className="shrink-0 text-right pr-2 select-none text-[var(--text-tertiary)]"
              style={{ width: `${lineNumWidth + 1}ch` }}
            >
              {i + 1}
            </span>
            <span className="whitespace-pre-wrap break-all text-[var(--text-primary)]">{line || " "}</span>
          </div>
        ))}
      </div>
      {shouldCollapse && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="w-full flex items-center justify-center gap-1 py-1.5 border-t border-[var(--border-subtle)] text-[11px] text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
        >
          <ChevronDown size={12} className={cn(expanded && "rotate-180 transition-transform")} />
          {expanded ? _t("toolResult.collapse") : _t("toolResult.showMoreLines", { count: lines.length - maxLines })}
        </button>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// 4. Bash — Terminal emulation
// ---------------------------------------------------------------------------

function BashRender({ args, result, accentVar }: { args: Record<string, unknown>; result: string; accentVar: string }) {
  const command = str(args.command) || "";
  const lines = result.split("\n");
  const err = isError(result);
  const exitCode = err ? 1 : 0;

  // Extract exit code from result if present
  const exitMatch = result.match(/exit code[:\s]+(\d+)/i);
  const detectedExit = exitMatch ? parseInt(exitMatch[1]) : exitCode;

  const [expanded, setExpanded] = useState(false);
  const maxOutputLines = 30;
  const shouldCollapse = lines.length > maxOutputLines + 2;
  const visibleLines = shouldCollapse && !expanded ? lines.slice(0, maxOutputLines) : lines;

  return (
    <Container accentVar={accentVar}>
      <Header icon={<Terminal size={13} />} title={_t("toolResult.terminal")} />
      {/* Command line */}
      {command && (
        <div className="px-3 py-1.5 bg-[var(--code-bg)] border-b border-[var(--border-subtle)]">
          <span className="text-[var(--success)] font-mono text-[12px] font-bold">$ </span>
          <span className="text-[var(--text-primary)] font-mono text-[12px]">{command}</span>
        </div>
      )}
      {/* Output */}
      <div className="py-1 bg-[var(--code-bg)]">
        {visibleLines.map((line, i) => (
          <div key={i} className="px-3 text-[12px] font-mono leading-[1.5] text-[var(--text-secondary)] whitespace-pre-wrap break-all">
            {line || "\u00A0"}
          </div>
        ))}
      </div>
      {shouldCollapse && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="w-full flex items-center justify-center gap-1 py-1.5 border-t border-[var(--border-subtle)] text-[11px] text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
        >
          <ChevronDown size={12} className={cn(expanded && "rotate-180 transition-transform")} />
          {expanded ? _t("toolResult.collapse") : _t("toolResult.showMoreLines", { count: lines.length - maxOutputLines })}
        </button>
      )}
      {/* Exit status */}
      <div className={cn("flex items-center gap-1.5 px-3 py-1.5 text-[11px] border-t border-[var(--border-subtle)]",
        detectedExit === 0 ? "text-[var(--success)]" : "text-[var(--danger)]"
      )}>
        {detectedExit === 0 ? <Check size={12} /> : <AlertTriangle size={12} />}
        Exit code: {detectedExit}
      </div>
    </Container>
  );
}

// ---------------------------------------------------------------------------
// 5. Grep — Search results
// ---------------------------------------------------------------------------

function GrepRender({ args, result, accentVar }: { args: Record<string, unknown>; result: string; accentVar: string }) {
  const pattern = str(args.pattern) || "";
  const err = isError(result);

  if (err) {
    return (
      <Container accentVar={accentVar}>
        <Header icon={<Search size={13} />} title={_t("toolResult.grep")} subtitle={pattern} />
        <div className="px-3 py-2 text-[12px] text-[var(--danger)]">{result}</div>
      </Container>
    );
  }

  const lines = result.split("\n").filter((l) => l.trim());
  const isNoMatch = result.trim() === "No matches found.";

  // Parse "filepath:linenum: content" format
  const parsed = lines.map((line) => {
    const match = line.match(/^(.+?):(\d+):\s*(.*)$/);
    if (match) return { file: match[1], lineNum: match[2], content: match[3] };
    return { file: "", lineNum: "", content: line };
  });

  return (
    <Container accentVar={accentVar}>
      <Header icon={<Search size={13} />} title={_t("toolResult.grep")} subtitle={`${pattern} → ${isNoMatch ? "0" : parsed.length} ${_t("toolResult.matches")}`} />
      {isNoMatch ? (
        <div className="px-3 py-3 text-[12px] text-[var(--text-tertiary)] text-center">{_t("toolResult.noMatches")}</div>
      ) : (
        <MatchList items={parsed} pattern={pattern} />
      )}
    </Container>
  );
}

function MatchList({ items, pattern }: { items: { file: string; lineNum: string; content: string }[]; pattern: string }) {
  const [expanded, setExpanded] = useState(false);
  const max = 10;
  const shouldCollapse = items.length > max + 2;
  const visible = shouldCollapse && !expanded ? items.slice(0, max) : items;

  return (
    <>
      <div className="py-1">
        {visible.map((item, i) => (
          <div key={i} className="px-3 py-0.5 border-b border-[var(--border-subtle)] last:border-b-0">
            <div className="text-[11px] font-mono text-[var(--accent)]">{item.file}<span className="text-[var(--text-tertiary)]">:{item.lineNum}</span></div>
            <div className="text-[12px] font-mono text-[var(--text-secondary)] truncate">
              <HighlightText text={item.content} pattern={pattern} />
            </div>
          </div>
        ))}
      </div>
      {shouldCollapse && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="w-full flex items-center justify-center gap-1 py-1.5 border-t border-[var(--border-subtle)] text-[11px] text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
        >
          <ChevronDown size={12} className={cn(expanded && "rotate-180 transition-transform")} />
          {expanded ? _t("toolResult.collapse") : _t("toolResult.showMoreMatches", { count: items.length - max })}
        </button>
      )}
    </>
  );
}

function HighlightText({ text, pattern }: { text: string; pattern: string }) {
  if (!pattern) return <>{text}</>;
  try {
    const parts: ReactNode[] = [];
    const regex = new RegExp(`(${pattern.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi");
    let lastIdx = 0;
    let match: RegExpExecArray | null;
    let key = 0;
    while ((match = regex.exec(text)) !== null) {
      if (match.index > lastIdx) parts.push(<span key={key++}>{text.slice(lastIdx, match.index)}</span>);
      parts.push(
        <span key={key++} className="bg-[var(--warning-bg)] text-[var(--warning)] rounded-sm px-0.5">{match[1]}</span>
      );
      lastIdx = match.index + match[0].length;
    }
    if (lastIdx < text.length) parts.push(<span key={key++}>{text.slice(lastIdx)}</span>);
    return <>{parts}</>;
  } catch {
    return <>{text}</>;
  }
}

// ---------------------------------------------------------------------------
// 6. Glob — File list
// ---------------------------------------------------------------------------

function GlobRender({ args, result, accentVar }: { args: Record<string, unknown>; result: string; accentVar: string }) {
  const pattern = str(args.pattern) || "";
  const err = isError(result);

  if (err) {
    return (
      <Container accentVar={accentVar}>
        <Header icon={<FolderOpen size={13} />} title={_t("toolResult.glob")} subtitle={pattern} />
        <div className="px-3 py-2 text-[12px] text-[var(--danger)]">{result}</div>
      </Container>
    );
  }

  const lines = result.split("\n").filter((l) => l.trim());
  const isNoMatch = result.trim() === "No files found.";

  return (
    <Container accentVar={accentVar}>
      <Header icon={<FolderOpen size={13} />} title={_t("toolResult.glob")} subtitle={`${pattern} → ${isNoMatch ? "0" : lines.length} ${_t("toolResult.files")}`} />
      {isNoMatch ? (
        <div className="px-3 py-3 text-[12px] text-[var(--text-tertiary)] text-center">{_t("toolResult.noFiles")}</div>
      ) : (
        <FileList lines={lines} />
      )}
    </Container>
  );
}

function FileList({ lines }: { lines: string[] }) {
  const [expanded, setExpanded] = useState(false);
  const max = 15;
  const shouldCollapse = lines.length > max + 2;
  const visible = shouldCollapse && !expanded ? lines.slice(0, max) : lines;

  return (
    <>
      <div className="py-1">
        {visible.map((line, i) => (
          <div key={i} className="px-3 py-0.5 text-[12px] font-mono text-[var(--text-secondary)] truncate border-b border-[var(--border-subtle)] last:border-b-0">
            {line}
          </div>
        ))}
      </div>
      {shouldCollapse && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="w-full flex items-center justify-center gap-1 py-1.5 border-t border-[var(--border-subtle)] text-[11px] text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
        >
          <ChevronDown size={12} className={cn(expanded && "rotate-180 transition-transform")} />
          {expanded ? _t("toolResult.collapse") : _t("toolResult.showMoreFiles", { count: lines.length - max })}
        </button>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// 7. Memory — Card style
// ---------------------------------------------------------------------------

function MemoryRender({ name, args, result, accentVar }: { name: string; args: Record<string, unknown>; result: string; accentVar: string }) {
  const memType = str(args.memory_type) || "";
  const key = str(args.key) || "";
  const category = str(args.category) || "";
  const content = str(args.content) || result;
  const err = isError(result);

  const typeColors: Record<string, string> = {
    team_knowledge: "var(--brand)",
    lesson: "var(--accent)",
    user_preference: "var(--accent-2)",
  };
  const typeColor = typeColors[memType] || "var(--accent)";

  return (
    <Container accentVar={accentVar}>
      <Header icon={<Save size={13} />} title={`${_t("toolResult.memory")} ${name.replace("memory_", "")}`} />
      <div className="px-3 py-2 space-y-1 text-[12px]">
        {memType && <KVRow label={_t("toolResult.type")} value={memType} />}
        {category && <KVRow label={_t("toolResult.category")} value={category} />}
        {key && <KVRow label={_t("toolResult.key")} value={key} />}
      </div>
      {!err && content && (
        <div className="px-3 py-2 border-t border-[var(--border-subtle)]">
          <div className="text-[12px] text-[var(--text-primary)] whitespace-pre-wrap break-words max-h-32 overflow-auto"
            style={{ borderLeft: `2px solid ${typeColor}`, paddingLeft: 8 }}>
            {content.slice(0, 500)}
            {content.length > 500 ? "…" : ""}
          </div>
        </div>
      )}
      {err && <div className="px-3 py-2 text-[12px] text-[var(--danger)] border-t border-[var(--border-subtle)]">{result}</div>}
    </Container>
  );
}

// ---------------------------------------------------------------------------
// 8. Web Search / Scrape
// ---------------------------------------------------------------------------

function WebRender({ name, args, result, accentVar }: { name: string; args: Record<string, unknown>; result: string; accentVar: string }) {
  const query = str(args.query) || str(args.url) || "";
  const err = isError(result);

  return (
    <Container accentVar={accentVar}>
      <Header icon={<Globe size={13} />} title={name === "web_search" ? _t("toolResult.webSearch") : _t("toolResult.webScrape")} subtitle={query.slice(0, 60)} />
      <div className="px-3 py-2">
        {err ? (
          <div className="text-[12px] text-[var(--danger)]">{result}</div>
        ) : (
          <div className="text-[12px] text-[var(--text-secondary)] whitespace-pre-wrap break-words max-h-48 overflow-auto">
            {result.slice(0, 1000)}
            {result.length > 1000 ? "…" : ""}
          </div>
        )}
      </div>
    </Container>
  );
}

// ---------------------------------------------------------------------------
// 9. Delegate / Pipeline — Markdown result
// ---------------------------------------------------------------------------

function DelegateRender({ name, args, result, accentVar }: { name: string; args: Record<string, unknown>; result: string; accentVar: string }) {
  const agentName = str(args.agent_name) || "";
  const task = str(args.task) || "";
  const steps = args.steps;
  const stepsArr: Array<Record<string, unknown>> | null = Array.isArray(steps) ? steps as Array<Record<string, unknown>> : null;
  const err = isError(result);
  const isPipeline = name === "run_pipeline" || name === "delegate_parallel";
  const displayName = isPipeline ? _t("toolResult.pipeline") : _t("toolResult.delegate");

  return (
    <Container accentVar={accentVar}>
      <Header
        icon={<GitBranch size={13} />}
        title={displayName}
        subtitle={agentName ? `→ ${agentName}` : ""}
      />
      {task && (
        <div className="px-3 py-1.5 text-[11px] text-[var(--text-secondary)] border-b border-[var(--border-subtle)] truncate">
          Task: {task.slice(0, 120)}
        </div>
      )}
      {stepsArr && (
        <div className="px-3 py-1.5 border-b border-[var(--border-subtle)]">
          {stepsArr.map((s: Record<string, unknown>, i: number) => (
            <div key={i} className="text-[11px] text-[var(--text-tertiary)] font-mono">
              {i + 1}. {str(s.agent_name)} → {str(s.task)?.slice(0, 60)}
            </div>
          ))}
        </div>
      )}
      <div className="px-3 py-2">
        {err ? (
          <div className="text-[12px] text-[var(--danger)]">{result}</div>
        ) : (
          <div className="markdown-body text-[13px] max-h-64 overflow-auto">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.slice(0, 3000)}</ReactMarkdown>
          </div>
        )}
      </div>
    </Container>
  );
}

// ---------------------------------------------------------------------------
// 10. Image Generate — show generated images inline from result JSON
// ---------------------------------------------------------------------------

function ImageGenerateRender({ args, result, images, onPreviewImage, accentVar }: {
  args: Record<string, unknown>; result: string; images?: string[]; onPreviewImage?: (url: string) => void; accentVar: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const err = isError(result);

  // Parse the JSON result to extract image info
  let parsed: Record<string, unknown> = {};
  let imageEntries: Array<Record<string, unknown>> = [];
  let provider = "";
  let model = "";
  let generated = 0;

  if (!err) {
    try {
      parsed = JSON.parse(result);
      imageEntries = (parsed.images as Array<Record<string, unknown>>) || [];
      provider = (parsed.provider as string) || "";
      model = (parsed.model as string) || "";
      generated = (parsed.generated as number) || 0;
    } catch {
      // fall through to generic display
    }
  }

  // If we couldn't parse images, fall back to generic
  if (imageEntries.length === 0) {
    return <GenericRender name="image_generate" args={args} result={result} images={images} onPreviewImage={onPreviewImage} accentVar={accentVar} />;
  }

  const prompt = (args.prompt as string) || "";

  // Convert file paths to /api/files/image URLs (same logic as dbMessagesToChat)
  const resolvedImages = imageEntries.map((entry) => {
    const path = (entry.path as string) || "";
    if (!path) return "";
    const token = (typeof localStorage !== "undefined" && localStorage.getItem("crab_token")) || "";
    return `/api/files/image?path=${encodeURIComponent(path)}&absolute=true&token=${encodeURIComponent(token)}`;
  }).filter(Boolean);

  return (
    <Container accentVar={accentVar}>
      <Header
        icon={<ImageIcon size={13} />}
        title="Image Generated"
        subtitle={generated > 0 ? `${generated} image${generated > 1 ? "s" : ""} · ${model}` : model}
      />
      {/* Prompt */}
      {prompt && (
        <div className="px-3 py-2 border-b border-[var(--border-subtle)]">
          <div className="text-[10px] uppercase tracking-wider text-[var(--text-tertiary)] mb-0.5">Prompt</div>
          <div className="text-[12px] text-[var(--text-secondary)] leading-relaxed">{prompt}</div>
        </div>
      )}
      {/* Images */}
      <div className="p-2 flex flex-wrap gap-2">
        {(resolvedImages.length > 0 ? resolvedImages : images || []).map((img, idx) => {
          if (!img) return null;
          return (
            <img
              key={idx}
              src={img}
              alt={`Generated ${idx + 1}`}
              className="max-w-full max-h-[300px] rounded-lg object-contain cursor-pointer border border-[var(--border)] hover:border-[var(--brand-border)] transition-colors"
              onClick={() => onPreviewImage?.(img)}
              onError={(e) => {
                // Hide broken image, show fallback text
                const target = e.currentTarget;
                target.style.display = "none";
                const fallback = target.nextElementSibling;
                if (fallback) (fallback as HTMLElement).style.display = "flex";
              }}
            />
          );
        })}
      </div>
      {/* Fallback: show file paths if images fail to load */}
      {imageEntries.length > 0 && (
        <div style={{ display: resolvedImages.length > 0 ? "none" : "flex" }}
          className="px-3 py-2 flex-col gap-1 border-t border-[var(--border-subtle)]">
          <div className="text-[10px] uppercase tracking-wider text-[var(--text-tertiary)] mb-0.5">Saved Files</div>
          {imageEntries.map((entry, i) => {
            const path = (entry.path as string) || (entry.filename as string) || `Image ${i + 1}`;
            return (
              <div key={i} className="text-[12px] font-mono text-[var(--text-secondary)] break-all">
                {path}
              </div>
            );
          })}
        </div>
      )}
      {/* Details: collapsed by default */}
      {parsed && Object.keys(parsed).length > 0 && (
        <>
          <button
            onClick={() => setExpanded((v) => !v)}
            className="w-full flex items-center justify-center gap-1 py-1.5 border-t border-[var(--border-subtle)] text-[11px] text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
          >
            <ChevronDown size={12} className={cn(expanded && "rotate-180 transition-transform")} />
            {expanded ? "Hide details" : "Show details"}
          </button>
          {expanded && (
            <div className="px-3 py-2 space-y-0.5 border-t border-[var(--border-subtle)]">
              <KVRow label="provider" value={provider} />
              <KVRow label="model" value={model} />
              <KVRow label="size" value={(parsed.size as string) || ""} />
              <KVRow label="quality" value={(parsed.quality as string) || ""} />
            </div>
          )}
        </>
      )}
      {err && (
        <div className="px-3 py-2 text-[12px] text-[var(--danger)] border-t border-[var(--border-subtle)]">
          {result}
        </div>
      )}
    </Container>
  );
}

// Simple image icon component
function ImageIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <polyline points="21 15 16 10 5 21" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// 11. Generic fallback — key:value args + result text
// ---------------------------------------------------------------------------

function GenericRender({ name, args, result, images, onPreviewImage, accentVar }: {
  name: string; args: Record<string, unknown>; result: string; images?: string[]; onPreviewImage?: (url: string) => void; accentVar: string;
}) {
  const entries = Object.entries(args);
  const err = isError(result);
  const resultShort = result.length <= 500;

  return (
    <Container accentVar={accentVar}>
      <Header icon={<Zap size={13} />} title={name} />
      {entries.length > 0 && (
        <div className="px-3 py-2 space-y-0.5 border-b border-[var(--border-subtle)]">
          {entries.map(([k, v]) => (
            <KVRow key={k} label={k} value={typeof v === "string" ? v : JSON.stringify(v)} />
          ))}
        </div>
      )}
      <div className="px-3 py-2">
        {err ? (
          <div className="text-[12px] text-[var(--danger)]">{result}</div>
        ) : (
          <>
            <pre className="text-[12px] whitespace-pre-wrap break-all leading-relaxed font-mono text-[var(--text-secondary)] m-0 bg-transparent! p-0! border-0! max-h-48 overflow-auto">
              {resultShort ? result : result.slice(0, 500) + "\n…"}
            </pre>
            {images && images.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {images.map((img, idx) => (
                  <img
                    key={idx}
                    src={img}
                    alt={`Result ${idx + 1}`}
                    className="max-w-full max-h-[200px] rounded-md object-contain cursor-pointer border border-[var(--border)] hover:border-[var(--brand-border)] transition-colors"
                    onClick={() => onPreviewImage?.(img)}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </Container>
  );
}

// ---------------------------------------------------------------------------
// Shared micro-components
// ---------------------------------------------------------------------------

function KVRow({ label, value }: { label: string; value: string }) {
  const displayVal = value.length > 120 ? value.slice(0, 120) + "…" : value;
  return (
    <div className="flex gap-2 text-[12px] font-mono">
      <span className="text-[var(--text-tertiary)] shrink-0 min-w-[60px]">{label}</span>
      <span className="text-[var(--text-primary)] break-all">{displayVal}</span>
    </div>
  );
}

function str(v: unknown): string {
  if (typeof v === "string") return v;
  if (v == null) return "";
  return String(v);
}

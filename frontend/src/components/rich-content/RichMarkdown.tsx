import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { CodeBlock } from "../ui";
import { ChartBlock, KpiBlock } from "./ChartBlock";
import { MermaidDiagram } from "./MermaidDiagram";

function extractText(node: any): string {
  if (node == null) return "";
  if (typeof node === "string") return node;
  if (Array.isArray(node)) return node.map(extractText).join("");
  return node.props?.children ? extractText(node.props.children) : "";
}

function languageOf(node: any): string {
  const className: string = node?.props?.className || "";
  return /language-([\w-]+)/.exec(className)?.[1]?.toLowerCase() || "";
}

function MarkdownPre({ children, isStreaming = false }: { children?: ReactNode; isStreaming?: boolean }) {
  const code = Array.isArray(children) ? children[0] : children;
  const language = languageOf(code);
  const source = extractText(code).replace(/\n$/, "");
  if (language === "mermaid") return <MermaidDiagram source={source} isStreaming={isStreaming} />;
  if (language === "crab-chart") return <ChartBlock source={source} isStreaming={isStreaming} />;
  if (language === "crab-kpi") return <KpiBlock source={source} isStreaming={isStreaming} />;
  return <CodeBlock language={language} code={source}>{code}</CodeBlock>;
}

function StreamingMarkdownPre({ children }: { children?: ReactNode }) {
  return <MarkdownPre isStreaming>{children}</MarkdownPre>;
}

const components = {
  a({ children, ...props }: any) { return <a {...props} target="_blank" rel="noopener noreferrer">{children}</a>; },
  pre: MarkdownPre,
};

const streamingComponents = {
  ...components,
  pre: StreamingMarkdownPre,
};

export function RichMarkdown({ children, isStreaming = false }: { children: string; isStreaming?: boolean }) {
  // Keep component identities stable while text deltas arrive. Recreating the
  // renderer remounts Recharts repeatedly and can trigger React 19 update loops.
  return <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]} components={isStreaming ? streamingComponents : components}>{children}</ReactMarkdown>;
}

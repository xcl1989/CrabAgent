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

function MarkdownPre({ children }: { children?: ReactNode }) {
  const code = Array.isArray(children) ? children[0] : children;
  const language = languageOf(code);
  const source = extractText(code).replace(/\n$/, "");
  if (language === "mermaid") return <MermaidDiagram source={source} />;
  if (language === "crab-chart") return <ChartBlock source={source} />;
  if (language === "crab-kpi") return <KpiBlock source={source} />;
  return <CodeBlock language={language} code={source}>{code}</CodeBlock>;
}

const components = {
  a({ children, ...props }: any) { return <a {...props} target="_blank" rel="noopener noreferrer">{children}</a>; },
  pre: MarkdownPre,
};

export function RichMarkdown({ children }: { children: string }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]} components={components}>{children}</ReactMarkdown>;
}

export interface ChatMessage {
  id: string;
  role: string;
  content: string;
  reasoning_content?: string;
  tool_calls?: unknown[];
  isStreaming?: boolean;
  stats?: { elapsed: number; model: string; tokens: number; iterations: number };
  confirm_id?: string;
  tool_name?: string;
  args_summary?: string;
  confirmed?: boolean;
  options?: string[];
  source?: "builtin" | "mcp";
  server_name?: string;
  images?: string[];
  sub_agent_id?: string;
  sub_agent_name?: string;
  sub_agent_display?: string;
  sub_agent_elapsed?: number;
  sub_agent_tokens?: number;
  sub_agent_iterations?: number;
  // LLM retry status
  retry_info?: {
    phase: "retrying" | "countdown" | "exhausted";
    message: string;
    attempt: number;
    max_attempts: number;
    remaining_seconds?: number;
    delay_seconds?: number;
  };
}

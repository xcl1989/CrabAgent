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
  tool_call_id?: string;
  args_summary?: string;
  confirmed?: boolean;
  options?: string[];
  source?: "builtin" | "mcp";
  server_name?: string;
  images?: string[];
  lazy_images?: boolean; // true when images need to be fetched separately
  db_message_id?: number; // original DB message ID for lazy image fetching
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

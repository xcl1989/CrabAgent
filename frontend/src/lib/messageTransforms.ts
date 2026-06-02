import { ChatMessage } from "../types/ChatMessage";
import { SSEEvent } from "../api/events";
import { Message } from "../api/sessions";

export function sseEventToMessages(event: SSEEvent, messages: ChatMessage[]): ChatMessage[] {
  const updated = [...messages];

  if (event.type === "text_delta") {
    const last = updated[updated.length - 1];
    if (last?.role === "assistant" && last.isStreaming) {
      last.content += (event.data.text as string) || "";
      return updated;
    }
    updated.push({ id: `s-${Date.now()}`, role: (event.data.role as string) || "assistant", content: (event.data.text as string) || "", isStreaming: true });
    return updated;
  }

  if (event.type === "thinking_delta") {
    const last = updated[updated.length - 1];
    if (last?.role === "thinking") {
      last.content += (event.data.text as string) || "";
      return updated;
    }
    updated.push({ id: `t-${Date.now()}`, role: "thinking", content: (event.data.text as string) || "" });
    return updated;
  }

  if (event.type === "text_done") {
    const fullText = (event.data.text as string) || "";
    return updated.map((m) =>
      m.isStreaming ? { ...m, content: fullText || m.content, isStreaming: false } : m
    );
  }

  if (event.type === "tool_call") {
    const callId = event.data.id as string;
    if (callId && messages.some((m) => m.id === `tc-${callId}`)) {
      return messages;
    }
    updated.push({
      id: callId ? `tc-${callId}` : `tc-${Date.now()}`,
      role: "tool_call",
      content: JSON.stringify({ name: event.data.name, arguments: event.data.arguments }),
      source: (event.data.source as "builtin" | "mcp") || "builtin",
      server_name: (event.data.server_name as string) || undefined,
    });
    return updated;
  }

  if (event.type === "tool_result") {
    const callId = event.data.id as string;
    if (callId && messages.some((m) => m.id === `tr-${callId}`)) {
      return messages;
    }
    updated.push({
      id: callId ? `tr-${callId}` : `tr-${Date.now()}`,
      role: "tool_result",
      content: (event.data.result as string) || "",
      source: (event.data.source as "builtin" | "mcp") || "builtin",
      server_name: (event.data.server_name as string) || undefined,
    });
    return updated;
  }

  if (event.type === "agent_error") {
    updated.push({ id: `e-${Date.now()}`, role: "error", content: (event.data.error as string) || "Unknown error" });
    return updated;
  }

  if (event.type === "tool_confirm_request") {
    updated.push({
      id: `cf-${event.data.confirm_id}`,
      role: "tool_confirm",
      content: "",
      confirm_id: event.data.confirm_id as string,
      tool_name: event.data.tool_name as string,
      args_summary: event.data.args_summary as string,
    });
    return updated;
  }

  if (event.type === "user_input_request") {
    const opts = event.data.options as string[] | undefined;
    updated.push({
      id: `in-${event.data.input_id}`,
      role: "user_input",
      content: (event.data.question as string) || "",
      confirm_id: event.data.input_id as string,
      options: opts && opts.length > 0 ? opts : undefined,
    });
    return updated;
  }

  if (event.type === "context_compressed") {
    const orig = event.data.original_count as number;
    const comp = event.data.compressed_count as number;
    updated.push({
      id: `cc-${Date.now()}`,
      role: "notice",
      content: `Context compressed: ${orig} → ${comp} messages`,
    });
    return updated;
  }

  if (event.type === "screenshot") {
    updated.push({
      id: `ss-${Date.now()}`,
      role: "screenshot",
      content: "",
      images: [(event.data.image as string) || ""],
    });
    return updated;
  }

  if (event.type === "sub_agent_start") {
    const subId = (event.data.sub_agent_id as string) || "";
    if (updated.some((m) => m.sub_agent_id === subId)) return updated;
    const name = (event.data.agent_name as string) || "";
    return [
      ...updated,
      {
        id: `sa-${subId}`,
        role: "sub_agent" as const,
        content: "",
        sub_agent_id: subId,
        sub_agent_name: name,
        sub_agent_display: (event.data.display_name as string) || name,
      },
    ];
  }

  if (event.type === "sub_agent_text_delta") {
    return messages;
  }

  if (event.type === "sub_agent_tool_call") {
    return messages;
  }

  if (event.type === "sub_agent_tool_result") {
    return messages;
  }

  if (event.type === "sub_agent_end") {
    const subId = (event.data.sub_agent_id as string) || "";
    const resultText = (event.data.result as string) || "";
    const idx = updated.findIndex(m => m.sub_agent_id === subId && m.role === "sub_agent");
    if (idx >= 0) {
      updated[idx] = {
        ...updated[idx],
        content: resultText || updated[idx].content || "(sub-agent produced no output)",
        sub_agent_elapsed: event.data.elapsed as number,
        sub_agent_tokens: event.data.tokens as number,
        sub_agent_iterations: event.data.iterations as number,
      };
      return updated;
    }
    return messages;
  }

  if (event.type === "sub_agent_tool_call") {
    const subId = (event.data.sub_agent_id as string) || "";
    const name = (event.data.name as string) || "";
    const args = JSON.stringify(event.data.arguments || {});
    const idx = updated.findIndex(m => m.sub_agent_id === subId && m.role === "sub_agent");
    if (idx < 0) return messages;
    updated[idx] = { ...updated[idx], content: updated[idx].content + `\n→ ${name}(${args.slice(0, 120)})\n` };
    return updated;
  }

  if (event.type === "sub_agent_tool_result") {
    const subId = (event.data.sub_agent_id as string) || "";
    const name = (event.data.name as string) || "";
    const result = (event.data.result as string) || "";
    const idx = updated.findIndex(m => m.sub_agent_id === subId && m.role === "sub_agent");
    if (idx < 0) return messages;
    updated[idx] = { ...updated[idx], content: updated[idx].content + `\n← ${name}: ${result.slice(0, 200)}${result.length > 200 ? "..." : ""}\n` };
    return updated;
  }

  if (event.type === "sub_agent_end") {
    const subId = (event.data.sub_agent_id as string) || "";
    const resultText = (event.data.result as string) || "";
    const idx = updated.findIndex(m => m.sub_agent_id === subId && m.role === "sub_agent");
    if (idx < 0) return messages;
    updated[idx] = {
      ...updated[idx],
      content: resultText || updated[idx].content || "(sub-agent produced no output)",
      sub_agent_elapsed: event.data.elapsed as number,
      sub_agent_tokens: event.data.tokens as number,
      sub_agent_iterations: event.data.iterations as number,
    };
    return updated;
  }

  return updated;
}

export function dbMessagesToChat(msgs: Message[]): ChatMessage[] {
  const result: ChatMessage[] = [];
  const pendingToolCalls: { id: string; name: string; args: unknown }[] = [];

  for (const m of msgs) {
    if (m.role === "stats" && m.content) {
      try {
        const raw = JSON.parse(m.content);
        result.push({
          id: `db-${m.id}`,
          role: "stats",
          content: "",
          stats: {
            elapsed: raw.elapsed_seconds ?? raw.elapsed ?? 0,
            model: raw.model ?? "",
            tokens: raw.tokens ?? 0,
            iterations: raw.iterations ?? 0,
          },
        });
      } catch {
        /* ignore */
      }
      continue;
    }

    if (m.role === "tool") {
      const tcId = m.tool_call_id as string | undefined;
      const matched = tcId ? pendingToolCalls.findIndex((tc) => tc.id === tcId) : -1;
      if (matched >= 0) {
        const tc = pendingToolCalls.splice(matched, 1)[0];
        result.push({
          id: `db-${m.id}-tc`,
          role: "tool_call",
          content: JSON.stringify({ name: tc.name, arguments: tc.args }),
        });
      }
      // v0.9 — tool results may carry list content (multimodal browser results)
      let toolContent = m.content || "";
      let toolImages: string[] | undefined;
      if (toolContent.startsWith("[")) {
        try {
          const blocks = JSON.parse(toolContent);
          if (Array.isArray(blocks)) {
            const textBlock = blocks.find((b: { type: string }) => b.type === "text");
            const imageBlocks = blocks.filter((b: { type: string }) => b.type === "image_url");
            if (textBlock) toolContent = textBlock.text || "";
            if (imageBlocks.length > 0)
              toolImages = imageBlocks.map(
                (b: { image_url?: { url?: string } }) => b.image_url?.url || "",
              );
          }
        } catch {
          /* keep original content */
        }
      }
      const toolResultMsg: ChatMessage = {
        id: `db-${m.id}`,
        role: "tool_result",
        content: toolContent,
      };
      if (toolImages && toolImages.length > 0) toolResultMsg.images = toolImages;
      result.push(toolResultMsg);
      continue;
    }

    if (m.role === "assistant" && m.tool_calls) {
      const tc = typeof m.tool_calls === "string" ? JSON.parse(m.tool_calls) : m.tool_calls;
      if (m.content || m.reasoning_content) {
        const base: ChatMessage = { id: `db-${m.id}-text`, role: "assistant", content: m.content || "" };
        if (m.reasoning_content) base.reasoning_content = m.reasoning_content;
        result.push(base);
      }
      for (const tcItem of tc as { function: { name?: string; arguments?: unknown }; id: string }[]) {
        const fn = tcItem.function || {};
        let args = fn.arguments;
        if (typeof args === "string") {
          try {
            args = JSON.parse(args);
          } catch {
            /* keep string */
          }
        }
        pendingToolCalls.push({ id: tcItem.id, name: fn.name || "", args: args || {} });
      }
      continue;
    }

    if (m.role === "sub_agent" && m.content) {
      try {
        const data = JSON.parse(m.content);
        if (typeof data.text === "string") {
          result.push({
            id: `db-${m.id}`,
            role: "sub_agent",
            content: data.text,
            sub_agent_name: data.agent_name || m.name || "",
            sub_agent_display: data.display_name || data.agent_name || m.name || "",
            sub_agent_elapsed: data.elapsed,
            sub_agent_tokens: data.tokens,
            sub_agent_iterations: data.iterations,
          });
        }
      } catch {
        result.push({
          id: `db-${m.id}`,
          role: "sub_agent",
          content: m.content,
          sub_agent_name: m.name || "",
          sub_agent_display: m.name || "",
        });
      }
      continue;
    }

    const base: ChatMessage = { id: `db-${m.id}`, role: m.role, content: m.content || "" };
    if (m.reasoning_content) base.reasoning_content = m.reasoning_content;
    if (m.role === "user" && m.content && m.content.startsWith("[{")) {
      try {
        const blocks = JSON.parse(m.content);
        if (Array.isArray(blocks)) {
          const textBlock = blocks.find((b: { type: string }) => b.type === "text");
          const imageBlocks = blocks.filter((b: { type: string }) => b.type === "image_url");
          if (textBlock) base.content = textBlock.text || "";
          if (imageBlocks.length > 0)
            base.images = imageBlocks.map((b: { image_url?: { url?: string } }) => b.image_url?.url || "");
        }
      } catch {
        /* keep original content */
      }
    }
    // v0.9 — tool messages may carry list content (multimodal browser results).
    // Extract embedded images for inline rendering.
    if (m.role === "tool" && m.content && m.content.startsWith("[")) {
      try {
        const blocks = JSON.parse(m.content);
        if (Array.isArray(blocks)) {
          const textBlock = blocks.find((b: { type: string }) => b.type === "text");
          const imageBlocks = blocks.filter((b: { type: string }) => b.type === "image_url");
          if (textBlock) base.content = textBlock.text || "";
          if (imageBlocks.length > 0)
            base.images = imageBlocks.map((b: { image_url?: { url?: string } }) => b.image_url?.url || "");
        }
      } catch {
        /* keep original content */
      }
    }
    result.push(base);
  }

  return result;
}

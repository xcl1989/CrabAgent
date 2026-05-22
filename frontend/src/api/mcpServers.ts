import { api } from "./client";

export interface McpServer {
  name: string;
  display_name: string;
  transport: "stdio" | "http";
  command: string;
  args: string[];
  url: string;
  env: Record<string, string>;
  headers: Record<string, string>;
  enabled: boolean;
}

export interface McpTool {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

export interface TestConnectionResult {
  success: boolean;
  error: string;
  tools: McpTool[];
}

export interface McpServerStatus {
  name: string;
  display_name: string;
  status: "connected" | "disconnected" | "error" | "connecting";
  tool_count: number;
  tools: McpTool[];
  error: string;
  connected_at: number | null;
}

export function listMcpServers(): Promise<McpServer[]> {
  return api.get("/mcp-servers");
}

export function createMcpServer(data: {
  name: string;
  display_name?: string;
  transport: "stdio" | "http";
  command?: string;
  args?: string[];
  url?: string;
  env?: Record<string, string>;
  headers?: Record<string, string>;
  enabled?: boolean;
}): Promise<McpServer> {
  return api.post("/mcp-servers", data);
}

export function updateMcpServer(
  name: string,
  data: {
    display_name?: string;
    transport?: string;
    command?: string;
    args?: string[];
    url?: string;
    env?: Record<string, string>;
    headers?: Record<string, string>;
    enabled?: boolean;
  },
): Promise<McpServer> {
  return api.patch(`/mcp-servers/${name}`, data);
}

export function deleteMcpServer(name: string): Promise<void> {
  return api.del(`/mcp-servers/${name}`);
}

export function testMcpServer(name: string): Promise<TestConnectionResult> {
  return api.post(`/mcp-servers/${name}/test`, {});
}

export function getMcpServerTools(name: string): Promise<McpTool[]> {
  return api.get(`/mcp-servers/${name}/tools`);
}

export function getMcpStatus(): Promise<McpServerStatus[]> {
  return api.get("/mcp-servers/status/list");
}

export function connectMcpServer(name: string): Promise<McpServerStatus> {
  return api.post(`/mcp-servers/${name}/connect`, {});
}

export function disconnectMcpServer(name: string): Promise<McpServerStatus> {
  return api.post(`/mcp-servers/${name}/disconnect`, {});
}

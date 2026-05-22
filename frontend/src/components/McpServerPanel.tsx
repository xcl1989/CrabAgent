import { useEffect, useState } from "react";
import * as mcpApi from "../api/mcpServers";
import { McpServer, McpServerStatus } from "../api/mcpServers";
import * as settingsApi from "../api/settings";

interface Props {
  servers: McpServer[];
  status: McpServerStatus[];
  onClose: () => void;
  onRefresh: () => void;
}

export default function McpServerPanel({ servers, status, onClose, onRefresh }: Props) {
  const [tab, setTab] = useState<"servers" | "settings">("servers");
  const [mode, setMode] = useState<"list" | "add">("list");
  const [formName, setFormName] = useState("");
  const [formDisplayName, setFormDisplayName] = useState("");
  const [formTransport, setFormTransport] = useState<"stdio" | "http">("stdio");
  const [formCommand, setFormCommand] = useState("");
  const [formArgs, setFormArgs] = useState("");
  const [formUrl, setFormUrl] = useState("");
  const [formEnv, setFormEnv] = useState("");
  const [formHeaders, setFormHeaders] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState<string | null>(null);

  const [searxngUrl, setSearxngUrl] = useState("");
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; result_count?: number; error?: string } | null>(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    settingsApi.getSettings().then((s) => {
      setSearxngUrl(s.searxng_url || "");
      setSettingsLoaded(true);
    }).catch(() => {
      setSettingsLoaded(true);
    });
  }, []);

  const resetForm = () => {
    setFormName("");
    setFormDisplayName("");
    setFormTransport("stdio");
    setFormCommand("");
    setFormArgs("");
    setFormUrl("");
    setFormEnv("");
    setFormHeaders("");
    setError(null);
  };

  const getStatus = (name: string): McpServerStatus | undefined => status.find((s) => s.name === name);

  const handleAdd = async () => {
    setError(null);
    if (!formName) {
      setError("Name is required");
      return;
    }
    if (formTransport === "stdio" && !formCommand) {
      setError("Command is required for stdio transport");
      return;
    }
    if (formTransport === "http" && !formUrl) {
      setError("URL is required for HTTP transport");
      return;
    }

    let parsedArgs: string[] = [];
    try {
      parsedArgs = formArgs.trim() ? JSON.parse(formArgs.trim()) : [];
      if (!Array.isArray(parsedArgs)) throw new Error();
    } catch {
      setError('Args must be a valid JSON array (e.g. ["-y", "@mcp/server"])');
      return;
    }

    let parsedEnv: Record<string, string> = {};
    if (formEnv.trim()) {
      try {
        parsedEnv = JSON.parse(formEnv.trim());
      } catch {
        setError('Env must be a valid JSON object (e.g. {"KEY": "value"})');
        return;
      }
    }

    let parsedHeaders: Record<string, string> = {};
    if (formHeaders.trim()) {
      try {
        parsedHeaders = JSON.parse(formHeaders.trim());
      } catch {
        setError("Headers must be a valid JSON object");
        return;
      }
    }

    try {
      await mcpApi.createMcpServer({
        name: formName,
        display_name: formDisplayName || formName,
        transport: formTransport,
        command: formCommand,
        args: parsedArgs,
        url: formUrl,
        env: parsedEnv,
        headers: parsedHeaders,
      });
      onRefresh();
      setMode("list");
      resetForm();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to add MCP server");
    }
  };

  const handleConnect = async (name: string) => {
    setActing(name);
    setError(null);
    try {
      await mcpApi.connectMcpServer(name);
      onRefresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to connect");
    } finally {
      setActing(null);
    }
  };

  const handleDisconnect = async (name: string) => {
    setActing(name);
    setError(null);
    try {
      await mcpApi.disconnectMcpServer(name);
      onRefresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to disconnect");
    } finally {
      setActing(null);
    }
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete MCP server "${name}"?`)) return;
    try {
      await mcpApi.deleteMcpServer(name);
      onRefresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  };

  const handleSaveSettings = async () => {
    setSaving(true);
    setTestResult(null);
    try {
      await settingsApi.updateSettings({ searxng_url: searxngUrl });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  };

  const handleTestSearxng = async () => {
    if (!searxngUrl) return;
    setTesting(true);
    setTestResult(null);
    try {
      const result = await settingsApi.testSearxng(searxngUrl);
      setTestResult(result);
    } catch (e: unknown) {
      setTestResult({ success: false, error: e instanceof Error ? e.message : "Test failed" });
    } finally {
      setTesting(false);
    }
  };

  const statusColor = (s: string) =>
    s === "connected" ? "#34d399" : s === "connecting" ? "#fbbf24" : s === "error" ? "#f87171" : "var(--text-secondary)";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.6)" }}>
      <div
        className="w-full max-w-lg rounded-xl p-6 max-h-[85vh] overflow-y-auto"
        style={{ background: "var(--bg-secondary)" }}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">MCP Servers</h2>
          <button onClick={onClose} className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Close
          </button>
        </div>

        <div className="flex gap-1 mb-4">
          <button
            onClick={() => { setTab("servers"); setError(null); }}
            className="flex-1 py-1.5 rounded-lg text-sm font-medium"
            style={{
              background: tab === "servers" ? "#4c1d95" : "var(--bg-tertiary)",
              color: tab === "servers" ? "#d8b4fe" : "var(--text-secondary)",
              border: `1px solid ${tab === "servers" ? "#7c3aed" : "var(--border)"}`,
            }}
          >
            Servers
          </button>
          <button
            onClick={() => { setTab("settings"); setError(null); setTestResult(null); }}
            className="flex-1 py-1.5 rounded-lg text-sm font-medium"
            style={{
              background: tab === "settings" ? "#4c1d95" : "var(--bg-tertiary)",
              color: tab === "settings" ? "#d8b4fe" : "var(--text-secondary)",
              border: `1px solid ${tab === "settings" ? "#7c3aed" : "var(--border)"}`,
            }}
          >
            Settings
          </button>
        </div>

        {error && (
          <div
            className="mb-3 px-3 py-2 rounded text-xs"
            style={{ background: "#2d1215", border: "1px solid #5c1d22", color: "#fca5a5" }}
          >
            {error}
          </div>
        )}

        {tab === "settings" ? (
          <>
            <div className="mb-3">
              <label className="text-xs block mb-1" style={{ color: "var(--text-secondary)" }}>
                SearXNG URL (optional)
              </label>
              <input
                value={searxngUrl}
                onChange={(e) => setSearxngUrl(e.target.value)}
                placeholder="http://localhost:8888"
                className="w-full px-3 py-2 rounded-lg text-sm outline-none font-mono"
                disabled={!settingsLoaded}
                style={{
                  background: "var(--bg-tertiary)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border)",
                }}
              />
              <div className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>
                If set, web_search uses SearXNG first. Otherwise DuckDuckGo is used automatically (no API key needed).
              </div>
            </div>

            <div className="flex gap-2 mb-3">
              <button
                onClick={handleSaveSettings}
                disabled={saving}
                className="flex-1 py-2 rounded-lg text-sm font-medium"
                style={{ background: "#7c3aed", color: "#fff" }}
              >
                {saving ? "Saving..." : "Save"}
              </button>
              <button
                onClick={handleTestSearxng}
                disabled={testing || !searxngUrl}
                className="flex-1 py-2 rounded-lg text-sm font-medium"
                style={{ background: "#0d2818", color: "#34d399" }}
              >
                {testing ? "Testing..." : "Test Connection"}
              </button>
            </div>

            {testResult && (
              <div
                className="px-3 py-2 rounded text-xs"
                style={{
                  background: testResult.success ? "#0d2818" : "#2d1215",
                  border: `1px solid ${testResult.success ? "#166534" : "#5c1d22"}`,
                  color: testResult.success ? "#34d399" : "#fca5a5",
                }}
              >
                {testResult.success
                  ? `Connected successfully! (${testResult.result_count} results returned)`
                  : `Connection failed: ${testResult.error}`}
              </div>
            )}
          </>
        ) : mode === "list" ? (
          <>
            {servers.length === 0 && (
              <div className="text-center py-6 text-sm" style={{ color: "var(--text-secondary)" }}>
                No MCP servers configured.
                <br />
                Add one to connect external tools via the Model Context Protocol.
              </div>
            )}
            {servers.map((s) => {
              const st = getStatus(s.name);
              const connStatus = st?.status || "disconnected";
              const connError = st?.error || "";
              const toolCount = st?.tool_count || 0;
              const isActing = acting === s.name;

              return (
                <div
                  key={s.name}
                  className="p-3 mb-2 rounded-lg"
                  style={{ background: "var(--bg-tertiary)", border: "1px solid var(--border)" }}
                >
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <span style={{ color: "#a78bfa", fontSize: "14px" }}>&#x1f50c;</span>
                      <span className="text-sm font-medium">{s.display_name || s.name}</span>
                      <span
                        className="text-xs px-1.5 py-0.5 rounded"
                        style={{
                          background: s.transport === "http" ? "#1e3a5f" : "#2d1f5e",
                          color: s.transport === "http" ? "#60a5fa" : "#a78bfa",
                        }}
                      >
                        {s.transport}
                      </span>
                      <span className="flex items-center gap-1 text-xs">
                        <span
                          style={{
                            display: "inline-block",
                            width: 6,
                            height: 6,
                            borderRadius: "50%",
                            background: statusColor(connStatus),
                          }}
                        />
                        <span style={{ color: statusColor(connStatus) }}>{connStatus}</span>
                        {connStatus === "connected" && toolCount > 0 && (
                          <span style={{ color: "var(--text-secondary)" }}>({toolCount} tools)</span>
                        )}
                      </span>
                    </div>
                  </div>

                  <div className="text-xs mb-1.5" style={{ color: "var(--text-secondary)" }}>
                    {s.transport === "stdio" ? (
                      <span style={{ fontFamily: "monospace" }}>
                        {s.command} {s.args.join(" ")}
                      </span>
                    ) : (
                      <span style={{ fontFamily: "monospace" }}>{s.url}</span>
                    )}
                  </div>

                  {connError && (
                    <div className="text-xs mb-1.5 px-2 py-1 rounded" style={{ color: "#fca5a5", background: "#2d1215" }}>
                      {connError}
                    </div>
                  )}

                  <div className="flex gap-1.5 justify-end">
                    {connStatus === "connected" && (
                      <button
                        onClick={() => handleDisconnect(s.name)}
                        disabled={isActing}
                        className="text-xs px-2.5 py-1 rounded"
                        style={{ background: "var(--bg-primary)", color: "var(--text-secondary)" }}
                      >
                        {isActing ? "..." : "Disconnect"}
                      </button>
                    )}
                    {(connStatus === "disconnected" || connStatus === "error") && (
                      <button
                        onClick={() => handleConnect(s.name)}
                        disabled={isActing}
                        className="text-xs px-2.5 py-1 rounded font-medium"
                        style={{ background: "#0d2818", color: "#34d399" }}
                      >
                        {isActing ? "..." : connStatus === "error" ? "Reconnect" : "Connect"}
                      </button>
                    )}
                    <button
                      onClick={() => handleDelete(s.name)}
                      className="text-xs px-2 py-1 rounded"
                      style={{ color: "var(--danger)" }}
                    >
                      Del
                    </button>
                  </div>
                </div>
              );
            })}
            <button
              onClick={() => {
                resetForm();
                setMode("add");
              }}
              className="w-full mt-2 py-2 rounded-lg text-sm font-medium"
              style={{ background: "#4c1d95", color: "#d8b4fe" }}
            >
              + Add MCP Server
            </button>
          </>
        ) : (
          <>
            <div className="mb-3">
              <label className="text-xs block mb-1" style={{ color: "var(--text-secondary)" }}>
                Name
              </label>
              <input
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="my-mcp-server"
                className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                style={{
                  background: "var(--bg-tertiary)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border)",
                }}
              />
            </div>

            <div className="mb-3">
              <label className="text-xs block mb-1" style={{ color: "var(--text-secondary)" }}>
                Display Name
              </label>
              <input
                value={formDisplayName}
                onChange={(e) => setFormDisplayName(e.target.value)}
                placeholder="My MCP Server"
                className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                style={{
                  background: "var(--bg-tertiary)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border)",
                }}
              />
            </div>

            <div className="mb-3">
              <label className="text-xs block mb-1" style={{ color: "var(--text-secondary)" }}>
                Transport
              </label>
              <div className="flex gap-2">
                <button
                  onClick={() => setFormTransport("stdio")}
                  className="flex-1 py-2 rounded-lg text-sm font-medium"
                  style={{
                    background: formTransport === "stdio" ? "#4c1d95" : "var(--bg-tertiary)",
                    color: formTransport === "stdio" ? "#d8b4fe" : "var(--text-secondary)",
                    border: `1px solid ${formTransport === "stdio" ? "#7c3aed" : "var(--border)"}`,
                  }}
                >
                  Stdio (local)
                </button>
                <button
                  onClick={() => setFormTransport("http")}
                  className="flex-1 py-2 rounded-lg text-sm font-medium"
                  style={{
                    background: formTransport === "http" ? "#4c1d95" : "var(--bg-tertiary)",
                    color: formTransport === "http" ? "#d8b4fe" : "var(--text-secondary)",
                    border: `1px solid ${formTransport === "http" ? "#7c3aed" : "var(--border)"}`,
                  }}
                >
                  HTTP (remote)
                </button>
              </div>
            </div>

            {formTransport === "stdio" ? (
              <>
                <div className="mb-3">
                  <label className="text-xs block mb-1" style={{ color: "var(--text-secondary)" }}>
                    Command
                  </label>
                  <input
                    value={formCommand}
                    onChange={(e) => setFormCommand(e.target.value)}
                    placeholder="npx / uvx / python"
                    className="w-full px-3 py-2 rounded-lg text-sm outline-none font-mono"
                    style={{
                      background: "var(--bg-tertiary)",
                      color: "var(--text-primary)",
                      border: "1px solid var(--border)",
                    }}
                  />
                </div>
                <div className="mb-3">
                  <label className="text-xs block mb-1" style={{ color: "var(--text-secondary)" }}>
                    Args (JSON array)
                  </label>
                  <input
                    value={formArgs}
                    onChange={(e) => setFormArgs(e.target.value)}
                    placeholder='["-y", "@modelcontextprotocol/server-filesystem", "/path"]'
                    className="w-full px-3 py-2 rounded-lg text-xs outline-none font-mono"
                    style={{
                      background: "var(--bg-tertiary)",
                      color: "var(--text-primary)",
                      border: "1px solid var(--border)",
                    }}
                  />
                </div>
              </>
            ) : (
              <div className="mb-3">
                <label className="text-xs block mb-1" style={{ color: "var(--text-secondary)" }}>
                  URL
                </label>
                <input
                  value={formUrl}
                  onChange={(e) => setFormUrl(e.target.value)}
                  placeholder="https://example.com/mcp"
                  className="w-full px-3 py-2 rounded-lg text-sm outline-none font-mono"
                  style={{
                    background: "var(--bg-tertiary)",
                    color: "var(--text-primary)",
                    border: "1px solid var(--border)",
                  }}
                />
              </div>
            )}

            <div className="mb-3">
              <label className="text-xs block mb-1" style={{ color: "var(--text-secondary)" }}>
                Environment Variables (JSON object)
              </label>
              <textarea
                value={formEnv}
                onChange={(e) => setFormEnv(e.target.value)}
                placeholder='{"API_KEY": "sk-xxx"}'
                rows={2}
                className="w-full px-3 py-2 rounded-lg text-xs outline-none font-mono resize-none"
                style={{
                  background: "var(--bg-tertiary)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border)",
                }}
              />
            </div>

            {formTransport === "http" && (
              <div className="mb-4">
                <label className="text-xs block mb-1" style={{ color: "var(--text-secondary)" }}>
                  Headers (JSON object)
                </label>
                <textarea
                  value={formHeaders}
                  onChange={(e) => setFormHeaders(e.target.value)}
                  placeholder='{"Authorization": "Bearer xxx"}'
                  rows={2}
                  className="w-full px-3 py-2 rounded-lg text-xs outline-none font-mono resize-none"
                  style={{
                    background: "var(--bg-tertiary)",
                    color: "var(--text-primary)",
                    border: "1px solid var(--border)",
                  }}
                />
              </div>
            )}

            <div className="flex gap-2">
              <button
                onClick={() => {
                  setMode("list");
                  resetForm();
                }}
                className="flex-1 py-2 rounded-lg text-sm"
                style={{ background: "var(--bg-tertiary)", color: "var(--text-secondary)" }}
              >
                Cancel
              </button>
              <button
                onClick={handleAdd}
                className="flex-1 py-2 rounded-lg text-sm font-medium"
                style={{ background: "#7c3aed", color: "#fff" }}
              >
                Add Server
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

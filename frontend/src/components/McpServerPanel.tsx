import { useEffect, useState } from "react";
import { Plug, Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import * as mcpApi from "../api/mcpServers";
import { McpServer, McpServerStatus } from "../api/mcpServers";
import * as settingsApi from "../api/settings";
import {
  Modal,
  Button,
  Input,
  Textarea,
  ConfirmDialog,
  EmptyState,
} from "./ui";
import { toast } from "./ui/Toast";
import { cn } from "../lib/cn";

interface Props {
  servers: McpServer[];
  status: McpServerStatus[];
  onClose: () => void;
  onRefresh: () => void;
}

type Tab = "servers" | "settings";

export default function McpServerPanel({
  servers,
  status,
  onClose,
  onRefresh,
}: Props) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("servers");
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
  const [adding, setAdding] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const [searxngUrl, setSearxngUrl] = useState("");
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    result_count?: number;
    error?: string;
  } | null>(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    settingsApi
      .getSettings()
      .then((s) => {
        setSearxngUrl(s.searxng_url || "");
        setSettingsLoaded(true);
      })
      .catch(() => setSettingsLoaded(true));
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

  const getStatus = (name: string) => status.find((s) => s.name === name);

  const handleAdd = async () => {
    setError(null);
    if (!formName) return setError(t("mcp.nameRequired"));
    if (formTransport === "stdio" && !formCommand)
      return setError(t("mcp.commandRequired"));
    if (formTransport === "http" && !formUrl)
      return setError(t("mcp.urlRequired"));

    let parsedArgs: string[] = [];
    try {
      parsedArgs = formArgs.trim() ? JSON.parse(formArgs.trim()) : [];
      if (!Array.isArray(parsedArgs)) throw new Error();
    } catch {
      return setError(t("mcp.argsFormat"));
    }
    let parsedEnv: Record<string, string> = {};
    if (formEnv.trim()) {
      try {
        parsedEnv = JSON.parse(formEnv.trim());
      } catch {
        return setError(t("mcp.envFormat"));
      }
    }
    let parsedHeaders: Record<string, string> = {};
    if (formHeaders.trim()) {
      try {
        parsedHeaders = JSON.parse(formHeaders.trim());
      } catch {
        return setError(t("mcp.headersFormat"));
      }
    }

    setAdding(true);
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
      toast.success(t("mcp.serverAdded"));
      onRefresh();
      setMode("list");
      resetForm();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t("mcp.addFailed"));
    } finally {
      setAdding(false);
    }
  };

  const handleConnect = async (name: string) => {
    setActing(name);
    setError(null);
    try {
      await mcpApi.connectMcpServer(name);
      onRefresh();
    } catch (e: unknown) {
      toast.error(t("mcp.error"), {
        description: e instanceof Error ? e.message : undefined,
      });
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
      toast.error(t("mcp.error"), {
        description: e instanceof Error ? e.message : undefined,
      });
    } finally {
      setActing(null);
    }
  };

  const handleDelete = async (name: string) => {
    try {
      await mcpApi.deleteMcpServer(name);
      toast.success(t("mcp.testSuccess"));
      onRefresh();
    } catch (e: unknown) {
      toast.error(t("mcp.error"), {
        description: e instanceof Error ? e.message : undefined,
      });
    } finally {
      setDeleteTarget(null);
    }
  };

  const handleSaveSettings = async () => {
    setSaving(true);
    setTestResult(null);
    try {
      await settingsApi.updateSettings({ searxng_url: searxngUrl });
      toast.success(t("mcp.settingsSaved"));
    } catch (e: unknown) {
      toast.error(t("mcp.testFailed"));
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
      setTestResult({
        success: false,
        error: e instanceof Error ? e.message : t("mcp.testFailed"),
      });
    } finally {
      setTesting(false);
    }
  };

  const statusColor = (s: string) =>
    s === "connected"
      ? "var(--success)"
      : s === "connecting"
        ? "var(--warning)"
        : s === "error"
          ? "var(--danger)"
          : "var(--text-tertiary)";

  return (
    <>
      <Modal
        open={true}
        onOpenChange={(o) => !o && onClose()}
        title={t("mcp.title")}
        description={t("mcp.addServerDesc")}
        size="lg"
      >
        <div className="flex gap-1 p-1 bg-[var(--bg-tertiary)] rounded-lg mb-4">
          {(["servers", "settings"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => {
                setTab(t);
                setError(null);
                setTestResult(null);
              }}
              className={cn(
                "flex-1 py-1.5 rounded-md text-sm font-medium transition-all capitalize",
                tab === t
                  ? "bg-[var(--bg-secondary)] text-[var(--text-primary)] shadow-[var(--shadow-sm)]"
                  : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
              )}
            >
              {t}
            </button>
          ))}
        </div>

        {error && (
          <div className="mb-3 px-3 py-2 rounded-lg bg-[var(--danger-bg)] border border-[var(--danger-border)] text-xs text-[var(--danger)]">
            {error}
          </div>
        )}

        {tab === "settings" ? (
          <div className="space-y-3">
            <Input
              label="SearXNG URL (optional)"
              value={searxngUrl}
              onChange={(e) => setSearxngUrl(e.target.value)}
              placeholder="http://localhost:8888"
              disabled={!settingsLoaded}
              hint="If set, web_search uses SearXNG first. Otherwise DuckDuckGo is used (no API key needed)."
            />
            <div className="flex gap-2">
              <Button
                variant="secondary"
                onClick={handleSaveSettings}
                loading={saving}
              >
                Save
              </Button>
              <Button
                variant="outline"
                onClick={handleTestSearxng}
                loading={testing}
                disabled={!searxngUrl}
              >
                Test Connection
              </Button>
            </div>
            {testResult && (
              <div
                className={cn(
                  "px-3 py-2 rounded-lg text-xs",
                  testResult.success
                    ? "bg-[var(--success-bg)] border border-[var(--success-border)] text-[var(--success)]"
                    : "bg-[var(--danger-bg)] border border-[var(--danger-border)] text-[var(--danger)]",
                )}
              >
                {testResult.success
                  ? `Connected successfully! (${testResult.result_count} results returned)`
                  : `Connection failed: ${testResult.error}`}
              </div>
            )}
          </div>
        ) : mode === "list" ? (
          <div className="space-y-2">
            {servers.length === 0 ? (
              <EmptyState
                icon={<Plug size={28} />}
                title={t("mcp.noServers")}
                description="Add an MCP server to connect external tools."
                action={
                  <Button variant="brand" size="sm" onClick={() => setMode("add")}>
                    <Plus size={14} /> Add Server
                  </Button>
                }
              />
            ) : (
              <>
                {servers.map((s) => {
                  const st = getStatus(s.name);
                  const connStatus = st?.status || "disconnected";
                  const connError = st?.error || "";
                  const toolCount = st?.tool_count || 0;
                  const isActing = acting === s.name;
                  return (
                    <div
                      key={s.name}
                      className="p-3 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border)] hover:border-[var(--border-strong)] transition-colors"
                    >
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className="text-[var(--accent-2)]">
                          <Plug size={14} />
                        </span>
                        <span className="text-sm font-medium text-[var(--text-primary)] truncate">
                          {s.display_name || s.name}
                        </span>
                        <span
                          className={cn(
                            "text-[10px] px-1.5 py-0.5 rounded font-mono",
                            s.transport === "http"
                              ? "bg-[var(--accent-bg)] text-[var(--accent)]"
                              : "bg-[var(--accent-2-bg)] text-[var(--accent-2)]",
                          )}
                        >
                          {s.transport}
                        </span>
                        <span className="flex items-center gap-1 text-xs ml-auto">
                          <span
                            className="inline-block w-1.5 h-1.5 rounded-full"
                            style={{ background: statusColor(connStatus) }}
                          />
                          <span style={{ color: statusColor(connStatus) }}>
                            {connStatus}
                          </span>
                          {connStatus === "connected" && toolCount > 0 && (
                            <span className="text-[var(--text-tertiary)]">
                              ({toolCount} tools)
                            </span>
                          )}
                        </span>
                      </div>
                      <div className="text-xs mb-1.5 font-mono text-[var(--text-tertiary)] truncate">
                        {s.transport === "stdio"
                          ? `${s.command} ${s.args.join(" ")}`
                          : s.url}
                      </div>
                      {connError && (
                        <div className="text-[11px] mb-1.5 px-2 py-1 rounded bg-[var(--danger-bg)] text-[var(--danger)] break-words">
                          {connError}
                        </div>
                      )}
                      <div className="flex gap-1.5 justify-end">
                        {connStatus === "connected" && (
                          <Button
                            size="xs"
                            variant="ghost"
                            onClick={() => handleDisconnect(s.name)}
                            loading={isActing}
                          >
                            Disconnect
                          </Button>
                        )}
                        {(connStatus === "disconnected" ||
                          connStatus === "error") && (
                          <Button
                            size="xs"
                            variant="primary"
                            onClick={() => handleConnect(s.name)}
                            loading={isActing}
                          >
                            {connStatus === "error" ? t("mcp.testFailed") : t("mcp.connected")}
                          </Button>
                        )}
                        <Button
                          size="xs"
                          variant="ghost"
                          onClick={() => setDeleteTarget(s.name)}
                          className="text-[var(--danger)] hover:text-[var(--danger)] hover:bg-[var(--danger-bg)]"
                          title={t("common.delete")}
                        >
                          <Trash2 size={12} />
                        </Button>
                      </div>
                    </div>
                  );
                })}
                <Button
                  variant="secondary"
                  fullWidth
                  onClick={() => {
                    resetForm();
                    setMode("add");
                  }}
                >
                  <Plus size={14} /> Add MCP Server
                </Button>
              </>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <Input
              label={t("mcp.name")}
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              placeholder="my-mcp-server"
            />
            <Input
              label={t("mcp.displayName")}
              value={formDisplayName}
              onChange={(e) => setFormDisplayName(e.target.value)}
              placeholder={t("mcp.displayNamePlaceholder")}
            />
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-[var(--text-secondary)]">
                {t("mcp.transport")}
              </label>
              <div className="flex gap-1 p-1 bg-[var(--bg-tertiary)] rounded-lg">
                {(["stdio", "http"] as const).map((transportType) => (
                  <button
                    key={transportType}
                    onClick={() => setFormTransport(transportType)}
                    className={cn(
                      "flex-1 py-1.5 rounded-md text-xs font-medium transition-all",
                      formTransport === transportType
                        ? "bg-[var(--bg-secondary)] text-[var(--text-primary)] shadow-[var(--shadow-sm)]"
                        : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
                    )}
                  >
                    {transportType === "stdio" ? t("mcp.transportStdio") : t("mcp.transportHttp")}
                  </button>
                ))}
              </div>
            </div>

            {formTransport === "stdio" ? (
              <>
                <Input
                  label={t("mcp.command")}
                  value={formCommand}
                  onChange={(e) => setFormCommand(e.target.value)}
                  placeholder="npx / uvx / python"
                />
                <Input
                  label="Args (JSON array)"
                  value={formArgs}
                  onChange={(e) => setFormArgs(e.target.value)}
                  placeholder='["-y", "@modelcontextprotocol/server-filesystem", "/path"]'
                />
              </>
            ) : (
              <Input
                label={t("mcp.url")}
                value={formUrl}
                onChange={(e) => setFormUrl(e.target.value)}
                placeholder="https://example.com/mcp"
              />
            )}

            <Textarea
              label={t("mcp.environment")}
              value={formEnv}
              onChange={(e) => setFormEnv(e.target.value)}
              placeholder='{"API_KEY": "sk-xxx"}'
              rows={2}
            />

            {formTransport === "http" && (
              <Textarea
                label={t("mcp.headers")}
                value={formHeaders}
                onChange={(e) => setFormHeaders(e.target.value)}
                placeholder='{"Authorization": "Bearer xxx"}'
                rows={2}
              />
            )}

            <div className="flex gap-2 pt-2">
              <Button
                variant="ghost"
                onClick={() => {
                  setMode("list");
                  resetForm();
                }}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={handleAdd}
                loading={adding}
                fullWidth
              >
                Add Server
              </Button>
            </div>
          </div>
        )}
      </Modal>

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        title={`Delete MCP server "${deleteTarget}"?`}
        description=""
        confirmText={t("common.delete")}
        tone="danger"
        onConfirm={() => { if (deleteTarget) handleDelete(deleteTarget); }}
      />
    </>
  );
}

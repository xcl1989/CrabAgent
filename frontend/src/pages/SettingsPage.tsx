import { useTranslation } from "react-i18next";
import { useState, useEffect } from "react";
import { Save, FlaskConical, Search, Check, Smartphone, SlidersHorizontal, Globe, Wifi, Cat } from "lucide-react";
import { Input, Button } from "../components/ui";
import { toast } from "../components/ui/Toast";
import { cn } from "../lib/cn";
import * as settingsApi from "../api/settings";
import ModelSelector from "../components/ModelSelector";
import { SubAgentModelMapEditor, parseModelMap, serializeModelMap, type ModelMapRow } from "../components/SubAgentModelMapEditor";
import WeChatPanel from "../components/WeChatPanel";
import { PetsSettingsPanel } from "../components/PetsSettingsPanel";
import { useSettingsData } from "../hooks/useSettingsData";

type SettingsTab = "general" | "search" | "network" | "wechat" | "pets";

export default function SettingsPage() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<SettingsTab>("general");

  // Cached store — survives tab switches (no reload flash on re-mount).
  const { data, loading, updateSettings } = useSettingsData();

  // Local edit state — seeded from cache, updated as the user types.
  const [defaultModel, setDefaultModel] = useState("");
  const [defaultModelProvider, setDefaultModelProvider] = useState<string | undefined>(undefined);
  const [searxngUrl, setSearxngUrl] = useState("");
  const [globalProxy, setGlobalProxy] = useState("");
  const [webProxy, setWebProxy] = useState("");
  const [llmProxy, setLlmProxy] = useState("");
  const [browserProxy, setBrowserProxy] = useState("");
  const [subAgentMapRows, setSubAgentMapRows] = useState<ModelMapRow[]>([]);
  const [seeded, setSeeded] = useState(false);

  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testingProxy, setTestingProxy] = useState(false);

  // Seed local form state from cached data exactly once it's available,
  // and re-seed when the cache changes identity (e.g. provider invalidation).
  useEffect(() => {
    if (!data) return;
    const s = data.settings;
    setDefaultModel(s.default_model);
    setDefaultModelProvider(
      s.default_model_provider || resolveProviderForModel(data.providerModels, s.default_model),
    );
    setSearxngUrl(s.searxng_url);
    setGlobalProxy(s.proxy);
    setWebProxy(s.web_proxy);
    setLlmProxy(s.llm_proxy);
    setBrowserProxy(s.browser_proxy);
    setSubAgentMapRows(parseModelMap(s.sub_agent_model_map));
    setSeeded(true);
  }, [data]);

  const handleModelChange = (modelId: string, providerName: string) => {
    setDefaultModel(modelId);
    setDefaultModelProvider(providerName);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const data: Record<string, string> = {};
      if (defaultModel) {
        data.default_model = defaultModel;
        if (defaultModelProvider) {
          data.default_model_provider = defaultModelProvider;
        }
      } else {
        data.default_model = "";
        data.default_model_provider = "";
      }
      data.searxng_url = searxngUrl;
      data.proxy = globalProxy;
      data.web_proxy = webProxy;
      data.llm_proxy = llmProxy;
      data.browser_proxy = browserProxy;
      data.sub_agent_model_map = serializeModelMap(subAgentMapRows);
      await settingsApi.updateSettings(data);
      // Sync cache so the next visit shows saved values without refetch.
      updateSettings({
        default_model: defaultModel,
        default_model_provider: defaultModelProvider,
        searxng_url: searxngUrl,
        proxy: globalProxy,
        web_proxy: webProxy,
        llm_proxy: llmProxy,
        browser_proxy: browserProxy,
        sub_agent_model_map: data.sub_agent_model_map,
      });
      toast.success(t("settingsPage.saved"));
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const handleTestSearxng = async () => {
    if (!searxngUrl) return;
    setTesting(true);
    try {
      const result = await settingsApi.testSearxng(searxngUrl);
      if (result.success) {
        toast.success(
          t("settingsPage.testSuccess", { count: result.result_count ?? 0 }),
        );
      } else {
        toast.error(
          t("settingsPage.testFailed", { error: result.error ?? "unknown" }),
        );
      }
    } catch (e: unknown) {
      toast.error(
        t("settingsPage.testFailed", {
          error: e instanceof Error ? e.message : "unknown",
        }),
      );
    } finally {
      setTesting(false);
    }
  };

  const handleTestProxy = async () => {
    if (!globalProxy) return;
    setTestingProxy(true);
    try {
      const result = await settingsApi.testProxy(globalProxy);
      if (result.success) {
        toast.success(
          t("settingsPage.proxyTestSuccess", { latency: result.latency_ms ?? 0, ip: result.ip ?? "" }),
        );
      } else {
        toast.error(
          t("settingsPage.testFailed", { error: result.error ?? "unknown" }),
        );
      }
    } catch (e: unknown) {
      toast.error(
        t("settingsPage.testFailed", {
          error: e instanceof Error ? e.message : "unknown",
        }),
      );
    } finally {
      setTestingProxy(false);
    }
  };

  // Show the loading overlay only on the very first load (no cache yet).
  // Subsequent tab switches render immediately from the cached store.
  if (loading || !seeded || !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-sm text-[var(--text-tertiary)]">
          {t("common.loading")}
        </div>
      </div>
    );
  }

  const tabs: { id: SettingsTab; label: string; icon: React.ReactNode }[] = [
    { id: "general", label: t("settingsPage.sectionGeneral"), icon: <SlidersHorizontal size={14} /> },
    { id: "search", label: t("settingsPage.sectionSearch"), icon: <Search size={14} /> },
    { id: "network", label: t("settingsPage.sectionNetwork"), icon: <Globe size={14} /> },
    { id: "pets", label: t("settingsPage.sectionPets"), icon: <Cat size={14} /> },
    { id: "wechat", label: "微信渠道", icon: <Smartphone size={14} /> },
  ];

  const showSaveButton = activeTab === "general" || activeTab === "search" || activeTab === "network";

  return (
    <div className="h-full flex flex-col p-6 sm:p-8 max-w-2xl mx-auto">
      <h1 className="text-xl font-semibold text-[var(--text-primary)] mb-4">
        {t("settingsPage.title")}
      </h1>

      {/* Tab Bar */}
      <div className="flex gap-0.5 mb-6 border-b border-[var(--border)]">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              "flex items-center gap-1.5 px-4 py-2 text-sm font-medium transition-all",
              "border-b-2 -mb-px rounded-t-lg",
              activeTab === tab.id
                ? "border-[var(--brand)] text-[var(--brand)]"
                : "border-transparent text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]/50",
            )}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-y-auto pb-4">
        {activeTab === "general" && (
          <div className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5 space-y-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-[var(--text-secondary)]">
                {t("settingsPage.defaultModel")}
              </label>
              <div className="flex items-center gap-2">
                <ModelSelector
                  providerModels={data.providerModels}
                  selectedModel={defaultModel || ""}
                  selectedProvider={defaultModelProvider}
                  onChange={handleModelChange}
                  dropdownUpward={false}
                />
              </div>
              <p className="text-xs text-[var(--text-tertiary)]">
                {t("settingsPage.defaultModelDesc")}
              </p>
            </div>

            {/* Sub-Agent Model Map */}
            <div className="flex flex-col gap-1.5 pt-2 border-t border-[var(--border)]">
              <label className="text-xs font-medium text-[var(--text-secondary)]">
                {t("settingsPage.subAgentMapTitle")}
              </label>
              <p className="text-xs text-[var(--text-tertiary)] mb-1">
                {t("settingsPage.subAgentMapDesc")}
              </p>
              <SubAgentModelMapEditor
                rows={subAgentMapRows}
                onChange={setSubAgentMapRows}
                providerModels={data.providerModels}
              />
            </div>
          </div>
        )}

        {activeTab === "search" && (
          <div className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5 space-y-4">
            <Input
              label={t("settingsPage.searxngUrl")}
              hint={t("settingsPage.searxngUrlDesc")}
              placeholder={t("settingsPage.searxngUrlPlaceholder")}
              value={searxngUrl}
              onChange={(e) => setSearxngUrl(e.target.value)}
              leftIcon={<Search size={14} />}
            />
            <div className="flex gap-2 pt-1">
              <Button
                variant="secondary"
                size="sm"
                onClick={handleTestSearxng}
                disabled={!searxngUrl || testing}
              >
                {testing ? (
                  <>
                    <FlaskConical size={14} className="animate-spin" />
                    {t("settingsPage.testing")}
                  </>
                ) : (
                  <>
                    <FlaskConical size={14} />
                    {t("settingsPage.testSearxng")}
                  </>
                )}
              </Button>
            </div>
          </div>
        )}

        {activeTab === "network" && (
          <div className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5 space-y-4">
            <div className="flex items-center gap-2 mb-2">
              <Wifi size={14} className="text-[var(--brand)]" />
              <span className="text-xs font-medium text-[var(--text-secondary)]">
                {t("settingsPage.proxySectionTitle")}
              </span>
            </div>

            {/* Global Proxy */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-[var(--text-secondary)]">
                {t("settingsPage.globalProxy")}
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={globalProxy}
                  onChange={(e) => setGlobalProxy(e.target.value)}
                  placeholder="http://127.0.0.1:7890"
                  className="flex-1 h-9 px-3 text-sm rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--brand)] focus:ring-1 focus:ring-[var(--brand)]/30"
                />
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleTestProxy}
                  disabled={!globalProxy || testingProxy}
                >
                  {testingProxy ? (
                    <>
                      <FlaskConical size={14} className="animate-spin" />
                      {t("settingsPage.testing")}
                    </>
                  ) : (
                    <>
                      <FlaskConical size={14} />
                      {t("settingsPage.testProxy")}
                    </>
                  )}
                </Button>
              </div>
              <p className="text-xs text-[var(--text-tertiary)]">
                {t("settingsPage.globalProxyDesc")}
              </p>
            </div>

            {/* Divider */}
            <div className="border-t border-[var(--border)] pt-4">
              <p className="text-[11px] font-medium text-[var(--text-tertiary)] mb-3">
                {t("settingsPage.categoryProxyDesc")}
              </p>

              {/* Web Proxy */}
              <div className="flex flex-col gap-1.5 mb-3">
                <label className="text-xs font-medium text-[var(--text-secondary)]">
                  {t("settingsPage.webProxy")}
                </label>
                <input
                  type="text"
                  value={webProxy}
                  onChange={(e) => setWebProxy(e.target.value)}
                  placeholder={t("settingsPage.proxyPlaceholder")}
                  className="w-full h-9 px-3 text-sm rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--brand)] focus:ring-1 focus:ring-[var(--brand)]/30"
                />
              </div>

              {/* LLM Proxy */}
              <div className="flex flex-col gap-1.5 mb-3">
                <label className="text-xs font-medium text-[var(--text-secondary)]">
                  {t("settingsPage.llmProxy")}
                </label>
                <input
                  type="text"
                  value={llmProxy}
                  onChange={(e) => setLlmProxy(e.target.value)}
                  placeholder={t("settingsPage.proxyPlaceholder")}
                  className="w-full h-9 px-3 text-sm rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--brand)] focus:ring-1 focus:ring-[var(--brand)]/30"
                />
              </div>

              {/* Browser Proxy */}
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-medium text-[var(--text-secondary)]">
                  {t("settingsPage.browserProxy")}
                </label>
                <input
                  type="text"
                  value={browserProxy}
                  onChange={(e) => setBrowserProxy(e.target.value)}
                  placeholder={t("settingsPage.proxyPlaceholder")}
                  className="w-full h-9 px-3 text-sm rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--brand)] focus:ring-1 focus:ring-[var(--brand)]/30"
                />
              </div>
            </div>
          </div>
        )}

        {activeTab === "wechat" && <WeChatPanel />}

        {activeTab === "pets" && (
          <div className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5">
            <PetsSettingsPanel />
          </div>
        )}
      </div>

      {/* Save Button — only for general/search tabs */}
      {showSaveButton && (
        <div className="sticky bottom-0 py-3 bg-[var(--bg-primary)] border-t border-[var(--border)]">
          <Button
            variant="brand"
            onClick={handleSave}
            disabled={saving}
            className="w-full sm:w-auto"
          >
            {saving ? (
              <>
                <Save size={15} className="animate-spin" />
                {t("settingsPage.saving")}
              </>
            ) : (
              <>
                <Check size={15} />
                {t("settingsPage.save")}
              </>
            )}
          </Button>
        </div>
      )}
    </div>
  );
}

/** Find the provider name that owns a given model id, if any. */
function resolveProviderForModel(
  providerModels: { provider: { name: string }; models: { id: string }[] }[],
  modelId: string,
): string | undefined {
  if (!modelId) return undefined;
  for (const pm of providerModels) {
    if (pm.models.some((m) => m.id === modelId)) {
      return pm.provider.name;
    }
  }
  return undefined;
}

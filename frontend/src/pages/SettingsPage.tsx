import { useTranslation } from "react-i18next";
import { useState, useEffect } from "react";
import { Save, FlaskConical, Search, Check, Smartphone, SlidersHorizontal } from "lucide-react";
import { Input, Button } from "../components/ui";
import { toast } from "../components/ui/Toast";
import { cn } from "../lib/cn";
import * as settingsApi from "../api/settings";
import * as providersApi from "../api/providers";
import ModelSelector from "../components/ModelSelector";
import WeChatPanel from "../components/WeChatPanel";
import type { Provider, ModelInfo } from "../api/providers";

interface ProviderModels {
  provider: Provider;
  models: ModelInfo[];
}

type SettingsTab = "general" | "search" | "wechat";

export default function SettingsPage() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<SettingsTab>("general");

  // Settings state
  const [defaultModel, setDefaultModel] = useState("");
  const [defaultModelProvider, setDefaultModelProvider] = useState<string | undefined>(undefined);
  const [searxngUrl, setSearxngUrl] = useState("");
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  // Providers / models state
  const [providers, setProviders] = useState<Provider[]>([]);
  const [providerModels, setProviderModels] = useState<ProviderModels[]>([]);
  const [providersLoading, setProvidersLoading] = useState(true);

  // Load settings
  useEffect(() => {
    settingsApi
      .getSettings()
      .then((s) => {
        setDefaultModel(s.default_model || "");
        setDefaultModelProvider(s.default_model_provider || undefined);
        setSearxngUrl(s.searxng_url || "");
        setSettingsLoaded(true);
      })
      .catch(() => setSettingsLoaded(true));
  }, []);

  // Load providers & models
  useEffect(() => {
    providersApi.listProviders().then((p) => {
      setProviders(p);
      setProvidersLoading(false);
    });
  }, []);

  useEffect(() => {
    if (providers.length === 0) return;
    Promise.all(
      providers.map(async (provider) => {
        try {
          const models = await providersApi.getProviderModels(provider.name);
          return { provider, models };
        } catch {
          return { provider, models: [] };
        }
      }),
    ).then((results) => {
      setProviderModels(results.filter((r) => r.models.length > 0));
    });
  }, [providers]);

  // After both settings and models are loaded, resolve provider if not already set
  useEffect(() => {
    if (!settingsLoaded || providerModels.length === 0) return;
    if (defaultModel && !defaultModelProvider) {
      for (const pm of providerModels) {
        if (pm.models.some((m) => m.id === defaultModel)) {
          setDefaultModelProvider(pm.provider.name);
          break;
        }
      }
    }
  }, [settingsLoaded, providerModels, defaultModel, defaultModelProvider]);

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
      await settingsApi.updateSettings(data);
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

  const allReady = settingsLoaded && !providersLoading;

  if (!allReady) {
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
    { id: "wechat", label: "微信渠道", icon: <Smartphone size={14} /> },
  ];

  const showSaveButton = activeTab === "general" || activeTab === "search";

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
                  providerModels={providerModels}
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

        {activeTab === "wechat" && <WeChatPanel />}
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

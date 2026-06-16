import { useTranslation } from "react-i18next";
import { useState } from "react";
import { Plus, Trash2, Star, StarOff, ChevronDown, ChevronRight, X } from "lucide-react";
import { Provider, CatalogEntry } from "../api/providers";
import * as providersApi from "../api/providers";
import { Modal, Button, Input, PasswordInput, ConfirmDialog, EmptyState } from "./ui";
import { toast } from "./ui/Toast";
import { cn } from "../lib/cn";

interface Props {
  providers: Provider[];
  catalog: CatalogEntry[];
  onClose: () => void;
  onRefresh: () => void;
}

export default function ProviderPanel({
  providers,
  catalog,
  onClose,
  onRefresh,
}: Props) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<"list" | "add">("list");
  const [formType, setFormType] = useState(catalog[0]?.type || "");
  const [formVariantId, setFormVariantId] = useState<string>("");
  const [formName, setFormName] = useState("");
  const [formKey, setFormKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [expandedProvider, setExpandedProvider] = useState<string | null>(null);
  const [newModelInput, setNewModelInput] = useState<Record<string, string>>({});
  const [modelBusy, setModelBusy] = useState<string | null>(null);

  const handleAddExtraModel = async (providerName: string) => {
    const modelId = (newModelInput[providerName] || "").trim();
    if (!modelId) return;
    const provider = providers.find((p) => p.name === providerName);
    if (!provider) return;
    const current = provider.extra_models || [];
    if (current.includes(modelId)) {
      toast.error("Model already exists");
      return;
    }
    setModelBusy(providerName);
    try {
      await providersApi.updateProvider(providerName, {
        extra_models: [...current, modelId],
      });
      toast.success(`Added model: ${modelId}`);
      onRefresh();
      setNewModelInput({ ...newModelInput, [providerName]: "" });
    } catch {
      toast.error("Failed to add model");
    } finally {
      setModelBusy(null);
    }
  };

  const handleRemoveExtraModel = async (providerName: string, modelId: string) => {
    const provider = providers.find((p) => p.name === providerName);
    if (!provider) return;
    const current = provider.extra_models || [];
    setModelBusy(`${providerName}:${modelId}`);
    try {
      await providersApi.updateProvider(providerName, {
        extra_models: current.filter((m) => m !== modelId),
      });
      toast.success(`Removed model: ${modelId}`);
      onRefresh();
    } catch {
      toast.error("Failed to remove model");
    } finally {
      setModelBusy(null);
    }
  };

  const handleAdd = async () => {
    setError(null);
    if (!formName || !formKey || !formType) {
      setError("All fields required");
      return;
    }
    setBusy(true);
    try {
      await providersApi.createProvider({
        name: formName,
        type: formType,
        api_key: formKey,
        variant_id: formVariantId || undefined,
      });
      toast.success(t("provider.providerAdded"));
      onRefresh();
      setMode("list");
      setFormName("");
      setFormKey("");
      setFormVariantId("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to add provider");
    } finally {
      setBusy(false);
    }
  };

  const handleSetDefault = async (name: string) => {
    try {
      await providersApi.updateProvider(name, { is_default: true });
      toast.success(t("provider.defaultUpdated"));
      onRefresh();
    } catch {
      toast.error(t("provider.setDefaultFailed"));
    }
  };

  const handleDelete = async (name: string) => {
    try {
      await providersApi.deleteProvider(name);
      toast.success(t("provider.providerDeleted"));
      onRefresh();
    } catch {
      toast.error(t("provider.deleteFailed"));
    } finally {
      setDeleteTarget(null);
    }
  };

  const selectedCatalog = catalog.find((c) => c.type === formType);
  const selectedVariant = selectedCatalog?.variants.find((v) => v.id === formVariantId);
  const displayBaseUrl = selectedVariant?.base_url || selectedCatalog?.base_url;

  return (
    <>
      <Modal
        open={true}
        onOpenChange={(o) => !o && onClose()}
        title={mode === "list" ? t("provider.title") : t("provider.addProvider")}
        description={
          mode === "list"
            ? t("provider.manageDesc")
            : t("provider.configureDesc")
        }
        size="md"
        footer={
          mode === "add" ? (
            <>
              <Button variant="ghost" onClick={() => setMode("list")}>
                {t("common.cancel")}
              </Button>
              <Button variant="brand" loading={busy} onClick={handleAdd}>
                {t("provider.addProvider")}
              </Button>
            </>
          ) : (
            <Button variant="brand" onClick={() => setMode("add")}>
              <Plus size={14} /> {t("provider.addProvider")}
            </Button>
          )
        }
      >
        {mode === "list" ? (
          <div className="space-y-2">
            {providers.length === 0 ? (
              <EmptyState
                title={t("provider.noProviders")}
                description={t("provider.addProviderDesc")}
                action={
                  <Button variant="brand" size="sm" onClick={() => setMode("add")}>
                    <Plus size={14} /> {t("provider.addProvider")}
                  </Button>
                }
              />
            ) : (
              providers.map((p) => (
                <div
                  key={p.name}
                  className={cn(
                    "rounded-xl border border-[var(--border)]",
                    "bg-[var(--bg-tertiary)] overflow-hidden",
                  )}
                >
                  <div className="p-3 flex items-center justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-[var(--text-primary)] flex items-center gap-1.5">
                        <span className="truncate">{p.display_name}</span>
                        {p.is_default && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--brand-bg)] text-[var(--brand)] border border-[var(--brand-border)] flex items-center gap-1 shrink-0">
                            <Star size={9} /> default
                          </span>
                        )}
                        {(p.extra_models?.length ?? 0) > 0 && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-secondary)] text-[var(--text-tertiary)] border border-[var(--border)] shrink-0">
                            +{p.extra_models!.length} 模型
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-[var(--text-tertiary)] font-mono truncate">
                        {p.type} · {p.api_key_preview}
                      </div>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setExpandedProvider(expandedProvider === p.name ? null : p.name)}
                        title="额外模型"
                      >
                        {expandedProvider === p.name ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      </Button>
                      {!p.is_default && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleSetDefault(p.name)}
                          title={t("provider.setAsDefault")}
                        >
                          <StarOff size={14} />
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setDeleteTarget(p.name)}
                        title={t("common.delete")}
                        className="text-[var(--danger)] hover:text-[var(--danger)] hover:bg-[var(--danger-bg)]"
                      >
                        <Trash2 size={14} />
                      </Button>
                    </div>
                  </div>
                  {expandedProvider === p.name && (
                    <div className="px-3 pb-3 pt-1 border-t border-[var(--border)] space-y-2">
                      <div className="text-[11px] font-medium text-[var(--text-secondary)] pt-1.5">
                        额外模型（API 未返回但可调用的模型）
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {(p.extra_models || []).map((m) => (
                          <span
                            key={m}
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-[var(--bg-secondary)] border border-[var(--border)] text-xs text-[var(--text-primary)] font-mono"
                          >
                            {m}
                            <button
                              onClick={() => handleRemoveExtraModel(p.name, m)}
                              disabled={modelBusy === `${p.name}:${m}`}
                              className="text-[var(--text-tertiary)] hover:text-[var(--danger)] transition-colors"
                            >
                              <X size={11} />
                            </button>
                          </span>
                        ))}
                        {(p.extra_models || []).length === 0 && (
                          <span className="text-[11px] text-[var(--text-tertiary)]">暂无额外模型</span>
                        )}
                      </div>
                      <div className="flex items-center gap-1.5">
                        <input
                          type="text"
                          value={newModelInput[p.name] || ""}
                          onChange={(e) => setNewModelInput({ ...newModelInput, [p.name]: e.target.value })}
                          onKeyDown={(e) => { if (e.key === "Enter") handleAddExtraModel(p.name); }}
                          placeholder="输入模型 ID，如 glm-5.2"
                          className="flex-1 h-8 px-2.5 text-xs rounded-lg bg-[var(--bg-secondary)] border border-[var(--border)] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--brand)] focus:ring-1 focus:ring-[var(--brand)]/30"
                        />
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => handleAddExtraModel(p.name)}
                          loading={modelBusy === p.name}
                        >
                          <Plus size={12} />
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        ) : (
          <div className="space-y-4">
            {error && (
              <div className="px-3 py-2 rounded-lg bg-[var(--danger-bg)] border border-[var(--danger-border)] text-xs text-[var(--danger)]">
                {error}
              </div>
            )}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-[var(--text-secondary)]">
                Type
              </label>
              <select
                value={formType}
                onChange={(e) => {
                  setFormType(e.target.value);
                  setFormVariantId("");
                }}
                className="w-full h-9 px-3 text-sm rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--brand)] focus:ring-2 focus:ring-[var(--brand)]/30"
              >
                {catalog.map((c) => (
                  <option key={c.type} value={c.type}>
                    {c.display_name}
                  </option>
                ))}
              </select>
              {selectedCatalog && (
                <p className="text-[11px] text-[var(--text-tertiary)] font-mono">
                  Base URL: {displayBaseUrl}
                </p>
              )}
            </div>
            {selectedCatalog && selectedCatalog.variants.length > 0 && (
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-[var(--text-secondary)]">
                  Variant
                </label>
                <select
                  value={formVariantId}
                  onChange={(e) => setFormVariantId(e.target.value)}
                  className="w-full h-9 px-3 text-sm rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--brand)] focus:ring-2 focus:ring-[var(--brand)]/30"
                >
                  <option value="">{t("provider.defaultLabel")}</option>
                  {selectedCatalog.variants.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.display_name}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <Input
              label={t("provider.name")}
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              placeholder={t("provider.namePlaceholder2")}
            />
            <PasswordInput
              label={t("provider.apiKey")}
              value={formKey}
              onChange={(e) => setFormKey(e.target.value)}
              placeholder={t("provider.apiKeyPlaceholder2")}
            />
          </div>
        )}
      </Modal>

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        title={`Delete provider "${deleteTarget}"?`}
        description={t("provider.deleteProviderDesc")}
        confirmText={t("common.delete")}
        tone="danger"
        onConfirm={() => { if (deleteTarget) handleDelete(deleteTarget); }}
      />
    </>
  );
}

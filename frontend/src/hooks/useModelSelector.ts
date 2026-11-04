import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import * as providersApi from "../api/providers";
import { Provider, CatalogEntry, ModelInfo } from "../api/providers";
import { onProvidersChanged } from "../lib/providerSync";

export interface ProviderModels {
  provider: Provider;
  models: ModelInfo[];
}

// Providers publish new model slugs without notice (e.g. gpt-6.1-terra appears
// mid-session). ChatPage stays mounted for the whole app session, so a
// mount-only fetch leaves the dropdown stale until a full reload. Poll past the
// backend's own 10-minute model cache, and refresh on focus (throttled).
const MODEL_REFRESH_MS = 15 * 60 * 1000;
const MODEL_FOCUS_REFRESH_MS = 60 * 1000;

export function useModelSelector() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [providerModels, setProviderModels] = useState<ProviderModels[]>([]);
  const [providersLoading, setProvidersLoading] = useState(true);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState<string>("");
  const [selectedModel, setSelectedModel] = useState<string>("");
  const lastLoadedAt = useRef(0);

  const refreshProviders = useCallback(async () => {
    setProvidersLoading(true);
    try {
      const nextProviders = await providersApi.listProviders();
      setProviders(nextProviders);
    } finally {
      setProvidersLoading(false);
    }
  }, []);

  // Flat list for backward compatibility
  const models = useMemo(
    () => providerModels.flatMap((pm) => pm.models),
    [providerModels]
  );

  useEffect(() => {
    refreshProviders();
    providersApi.getCatalog().then(setCatalog);
  }, [refreshProviders]);

  useEffect(() => onProvidersChanged(() => {
    lastLoadedAt.current = 0;
    refreshProviders();
  }), [refreshProviders]);

  /** Fetch every provider's model list. Silent unless `showSpinner`. */
  const refreshModels = useCallback(async (showSpinner = false) => {
    if (providers.length === 0) return;
    if (showSpinner) setModelsLoading(true);
    setModelsError("");

    try {
      const results = await Promise.all(
        providers.map(async (provider) => {
          try {
            const models = await providersApi.getProviderModels(provider.name);
            return { provider, models };
          } catch (err) {
            console.error(`Failed to load models for provider ${provider.name}`, err);
            return { provider, models: [] };
          }
        })
      );
      lastLoadedAt.current = Date.now();
      const nonEmpty = results.filter((r) => r.models.length > 0);
      // Keep the previous (still usable) list when every provider failed.
      if (nonEmpty.length > 0) setProviderModels(nonEmpty);

      // Auto-select first model if nothing selected yet
      const allModels = results.flatMap((r) => r.models);
      if (allModels.length > 0) {
        setSelectedModel((prev) => prev || allModels[0].id);
      }
    } catch (err) {
      setModelsError(err instanceof Error ? err.message : String(err));
    } finally {
      if (showSpinner) setModelsLoading(false);
    }
  }, [providers]);

  useEffect(() => {
    void refreshModels(true);
  }, [refreshModels]);

  // Background refresh so newly published models show up without a reload.
  useEffect(() => {
    if (providers.length === 0) return;

    const timer = window.setInterval(() => {
      void refreshModels();
    }, MODEL_REFRESH_MS);

    const onFocus = () => {
      if (Date.now() - lastLoadedAt.current < MODEL_FOCUS_REFRESH_MS) return;
      void refreshModels();
    };
    window.addEventListener("focus", onFocus);

    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [providers, refreshModels]);

  return {
    providers,
    catalog,
    models,
    providerModels,
    providersLoading,
    modelsLoading,
    modelsError,
    selectedModel,
    setSelectedModel,
    setProviders,
    setProvidersLoading,
    refreshProviders,
  };
}

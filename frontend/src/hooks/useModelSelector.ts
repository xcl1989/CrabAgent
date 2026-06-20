import { useState, useEffect, useMemo, useCallback } from "react";
import * as providersApi from "../api/providers";
import { Provider, CatalogEntry, ModelInfo } from "../api/providers";
import { onProvidersChanged } from "../lib/providerSync";

export interface ProviderModels {
  provider: Provider;
  models: ModelInfo[];
}

export function useModelSelector() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [providerModels, setProviderModels] = useState<ProviderModels[]>([]);
  const [providersLoading, setProvidersLoading] = useState(true);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState<string>("");
  const [selectedModel, setSelectedModel] = useState<string>("");

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
    refreshProviders();
  }), [refreshProviders]);

  useEffect(() => {
    if (providers.length === 0) return;

    setModelsLoading(true);
    setModelsError("");

    Promise.all(
      providers.map(async (provider) => {
        try {
          const models = await providersApi.getProviderModels(provider.name);
          return { provider, models };
        } catch (err) {
          console.error(`Failed to load models for provider ${provider.name}`, err);
          return { provider, models: [] };
        }
      })
    )
      .then((results) => {
        setProviderModels(results.filter((r) => r.models.length > 0));
        setModelsLoading(false);

        // Auto-select first model if nothing selected yet
        const allModels = results.flatMap((r) => r.models);
        if (allModels.length > 0) {
          setSelectedModel((prev) => prev || allModels[0].id);
        }
      })
      .catch((err) => {
        setModelsLoading(false);
        setModelsError(err instanceof Error ? err.message : String(err));
      });
  }, [providers]);

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

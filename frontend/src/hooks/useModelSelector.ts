import { useState, useEffect, useMemo } from "react";
import * as providersApi from "../api/providers";
import { Provider, CatalogEntry, ModelInfo } from "../api/providers";

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

  // Flat list for backward compatibility
  const models = useMemo(
    () => providerModels.flatMap((pm) => pm.models),
    [providerModels]
  );

  useEffect(() => {
    providersApi.listProviders().then((p) => {
      setProviders(p);
      setProvidersLoading(false);
    });
    providersApi.getCatalog().then(setCatalog);
  }, []);

  useEffect(() => {
    if (providers.length === 0) return;

    setModelsLoading(true);
    setModelsError("");

    Promise.all(
      providers.map(async (provider) => {
        try {
          const models = await providersApi.getProviderModels(provider.name);
          return { provider, models };
        } catch {
          return { provider, models: [] };
        }
      })
    )
      .then((results) => {
        setProviderModels(results.filter((r) => r.models.length > 0));
        setModelsLoading(false);

        // Auto-select first model if nothing selected yet
        const allModels = results.flatMap((r) => r.models);
        if (allModels.length > 0 && !selectedModel) {
          setSelectedModel(allModels[0].id);
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
  };
}

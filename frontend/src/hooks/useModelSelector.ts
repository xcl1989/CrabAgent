import { useState, useEffect } from "react";
import * as providersApi from "../api/providers";
import { Provider, CatalogEntry, ModelInfo } from "../api/providers";

export function useModelSelector() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [providersLoading, setProvidersLoading] = useState(true);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState<string>("");
  const [selectedModel, setSelectedModel] = useState<string>("");

  useEffect(() => {
    providersApi.listProviders().then((p) => {
      setProviders(p);
      setProvidersLoading(false);
    });
    providersApi.getCatalog().then(setCatalog);
  }, []);

  useEffect(() => {
    const defaultProvider = providers.find((p) => p.is_default);
    if (defaultProvider) {
      setModelsLoading(true);
      setModelsError("");
      providersApi
        .getProviderModels(defaultProvider.name)
        .then((m) => {
          setModels(m);
          setModelsLoading(false);
          if (m.length > 0 && !selectedModel) {
            setSelectedModel(m[0].id);
          }
        })
        .catch((err) => {
          setModelsLoading(false);
          setModelsError(err instanceof Error ? err.message : String(err));
        });
    }
  }, [providers]);

  return {
    providers,
    catalog,
    models,
    providersLoading,
    modelsLoading,
    modelsError,
    selectedModel,
    setSelectedModel,
    setProviders,
    setProvidersLoading,
  };
}

import { useState, useEffect } from "react";
import * as providersApi from "../api/providers";
import { Provider, CatalogEntry, ModelInfo } from "../api/providers";

export function useModelSelector() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [providersLoading, setProvidersLoading] = useState(true);
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
      providersApi
        .getProviderModels(defaultProvider.name)
        .then((m) => {
          setModels(m);
          if (m.length > 0 && !selectedModel) {
            setSelectedModel(m[0].id);
          }
        })
        .catch(() => {});
    }
  }, [providers]);

  return { providers, catalog, models, providersLoading, selectedModel, setSelectedModel, setProviders, setProvidersLoading };
}

/**
 * Cached settings + provider-models store.
 *
 * Motivation: SettingsPage is conditionally rendered (mounted/unmounted on
 * every tab switch). Without caching, each visit re-fetches `/settings`,
 * `/providers`, and one `/providers/:name/models` per provider — visibly slow.
 *
 * Strategy (cache-first, no silent overwrite of unsaved edits):
 *   - First load:  fetch from backend, populate module cache.
 *   - Re-mount:    reuse cache instantly (no loading flash, no background
 *                  request that could clobber in-progress edits).
 *   - External provider changes (`onProvidersChanged`): invalidate + reload.
 *   - Local save:  `updateSettings()` patches the cache in place.
 */

import { useState, useEffect, useCallback } from "react";
import * as settingsApi from "../api/settings";
import * as providersApi from "../api/providers";
import type { Provider, ModelInfo } from "../api/providers";
import { onProvidersChanged } from "../lib/providerSync";

export interface ProviderModels {
  provider: Provider;
  models: ModelInfo[];
}

export interface SettingsValues {
  default_model: string;
  default_model_provider?: string;
  searxng_url: string;
  proxy: string;
  web_proxy: string;
  llm_proxy: string;
  browser_proxy: string;
}

export interface SettingsData {
  settings: SettingsValues;
  providers: Provider[];
  providerModels: ProviderModels[];
}

let _cache: SettingsData | null = null;
let _inflight: Promise<SettingsData> | null = null;

async function fetchAll(): Promise<SettingsData> {
  const [raw, providers] = await Promise.all([
    settingsApi.getSettings(),
    providersApi.listProviders(),
  ]);
  const pmResults = await Promise.all(
    providers.map(async (provider) => {
      try {
        const models = await providersApi.getProviderModels(provider.name);
        return { provider, models };
      } catch (err) {
        console.error(`Failed to load models for provider ${provider.name}`, err);
        return { provider, models: [] };
      }
    }),
  );
  return {
    settings: {
      default_model: raw.default_model || "",
      default_model_provider: raw.default_model_provider || undefined,
      searxng_url: raw.searxng_url || "",
      proxy: raw.proxy || "",
      web_proxy: raw.web_proxy || "",
      llm_proxy: raw.llm_proxy || "",
      browser_proxy: raw.browser_proxy || "",
    },
    providers,
    providerModels: pmResults.filter((r) => r.models.length > 0),
  };
}

function getOrStartFetch(): Promise<SettingsData> {
  if (!_inflight) {
    _inflight = fetchAll()
      .then((d) => {
        _cache = d;
        return d;
      })
      .finally(() => {
        _inflight = null;
      });
  }
  return _inflight;
}

function invalidate() {
  _cache = null;
}

export function useSettingsData() {
  const [data, setData] = useState<SettingsData | null>(() => _cache);
  // loading only when we have nothing to show yet
  const [loading, setLoading] = useState<boolean>(() => !_cache);

  useEffect(() => {
    let mounted = true;
    // Cache hit: show immediately, no background refetch (protects unsaved edits).
    if (_cache) {
      setData(_cache);
      setLoading(false);
      return;
    }
    setLoading(true);
    getOrStartFetch()
      .then((d) => {
        if (mounted) {
          setData(d);
          setLoading(false);
        }
      })
      .catch(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  // Provider changes elsewhere (e.g. Agents page) → refresh.
  useEffect(() => {
    const off = onProvidersChanged(() => {
      invalidate();
      setLoading(true);
      getOrStartFetch()
        .then((d) => {
          setData(d);
          setLoading(false);
        })
        .catch(() => setLoading(false));
    });
    return off;
  }, []);

  /** Patch cached settings values (call after a successful save). */
  const updateSettings = useCallback((patch: Partial<SettingsValues>) => {
    if (!_cache) return;
    _cache = {
      ..._cache,
      settings: { ..._cache.settings, ...patch },
    };
    setData(_cache);
  }, []);

  /** Force a fresh fetch from the backend. */
  const reload = useCallback(() => {
    invalidate();
    setLoading(true);
    getOrStartFetch()
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  return { data, loading, updateSettings, reload };
}

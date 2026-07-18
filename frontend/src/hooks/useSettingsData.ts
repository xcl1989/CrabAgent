/**
 * Cached settings + provider-models store.
 *
 * Motivation: SettingsPage is conditionally rendered (mounted/unmounted on
 * every tab switch). Without caching, each visit re-fetches `/settings`,
 * `/providers`, and one `/providers/:name/models` per provider — visibly slow.
 *
 * Two independent loading tracks (so model selectors don't block the form):
 *   - settings  (fast)  → fills SearXNG / proxy / default-model-id fields.
 *   - providers (slow)  → fills ModelSelector dropdown lists.
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
import type { Provider } from "../api/providers";
import { onProvidersChanged } from "../lib/providerSync";
import type { ProviderModels } from "./useModelSelector";

export type { ProviderModels };

export interface SettingsValues {
  default_model: string;
  default_model_provider?: string;
  searxng_url: string;
  proxy: string;
  web_proxy: string;
  llm_proxy: string;
  browser_proxy: string;
  sub_agent_model_map: string;
}

// ── Settings cache (fast track) ──────────────────────────────────────────

let _settingsCache: SettingsValues | null = null;
let _settingsInflight: Promise<SettingsValues> | null = null;

function normalizeSettings(raw: Record<string, string>): SettingsValues {
  return {
    default_model: raw.default_model || "",
    default_model_provider: raw.default_model_provider || undefined,
    searxng_url: raw.searxng_url || "",
    proxy: raw.proxy || "",
    web_proxy: raw.web_proxy || "",
    llm_proxy: raw.llm_proxy || "",
    browser_proxy: raw.browser_proxy || "",
    sub_agent_model_map: raw.sub_agent_model_map || "",
  };
}

function fetchSettings(): Promise<SettingsValues> {
  return settingsApi.getSettings().then(normalizeSettings);
}

function getOrStartSettingsFetch(): Promise<SettingsValues> {
  if (!_settingsInflight) {
    _settingsInflight = fetchSettings()
      .then((s) => {
        _settingsCache = s;
        return s;
      })
      .finally(() => {
        _settingsInflight = null;
      });
  }
  return _settingsInflight;
}

// ── Providers cache (slow track) ─────────────────────────────────────────

let _providersCache: ProviderModels[] | null = null;
let _providersInflight: Promise<ProviderModels[]> | null = null;

async function fetchProviderModels(): Promise<ProviderModels[]> {
  const providers = await providersApi.listProviders();
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
  return pmResults.filter((r) => r.models.length > 0);
}

function getOrStartProvidersFetch(): Promise<ProviderModels[]> {
  if (!_providersInflight) {
    _providersInflight = fetchProviderModels()
      .then((pm) => {
        _providersCache = pm;
        return pm;
      })
      .finally(() => {
        _providersInflight = null;
      });
  }
  return _providersInflight;
}

// ── Hook ─────────────────────────────────────────────────────────────────

export function useSettingsData() {
  const [settings, setSettings] = useState<SettingsValues | null>(() => _settingsCache);
  const [providerModels, setProviderModels] = useState<ProviderModels[]>(() => _providersCache ?? []);
  const [settingsLoading, setSettingsLoading] = useState<boolean>(() => !_settingsCache);
  const [providersLoading, setProvidersLoading] = useState<boolean>(() => !_providersCache);
  const [providersError, setProvidersError] = useState(false);

  // Load settings (fast).
  useEffect(() => {
    let mounted = true;
    if (_settingsCache) {
      setSettings(_settingsCache);
      setSettingsLoading(false);
      return;
    }
    setSettingsLoading(true);
    getOrStartSettingsFetch()
      .then((s) => {
        if (mounted) {
          setSettings(s);
          setSettingsLoading(false);
        }
      })
      .catch(() => {
        if (mounted) setSettingsLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  // Load providers (slow, independent).
  useEffect(() => {
    let mounted = true;
    if (_providersCache) {
      setProviderModels(_providersCache);
      setProvidersLoading(false);
      return;
    }
    setProvidersLoading(true);
    getOrStartProvidersFetch()
      .then((pm) => {
        if (mounted) {
          setProviderModels(pm);
          setProvidersLoading(false);
        }
      })
      .catch(() => {
        if (mounted) {
          setProvidersLoading(false);
          setProvidersError(true);
        }
      });
    return () => {
      mounted = false;
    };
  }, []);

  // Provider changes elsewhere (e.g. Agents page) → reload the slow track.
  useEffect(() => {
    const off = onProvidersChanged(() => {
      _providersCache = null;
      setProvidersLoading(true);
      getOrStartProvidersFetch()
        .then((pm) => {
          setProviderModels(pm);
          setProvidersLoading(false);
        })
        .catch(() => setProvidersLoading(false));
    });
    return off;
  }, []);

  /** Patch cached settings values (call after a successful save). */
  const updateSettings = useCallback((patch: Partial<SettingsValues>) => {
    if (!_settingsCache) return;
    _settingsCache = { ..._settingsCache, ...patch };
    setSettings(_settingsCache);
  }, []);

  return {
    settings,
    providerModels,
    settingsLoading,
    providersLoading,
    providersError,
    updateSettings,
  };
}

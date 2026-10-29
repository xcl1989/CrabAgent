import type { ProviderModels } from "../hooks/useModelSelector";

const legacyEfforts = ["low", "medium", "high"];

export function reasoningOptions(providerModels: ProviderModels[], providers: { name: string; type: string; is_default: boolean }[], providerName: string | null, model: string): string[] {
  const provider = providers.find((p) => p.name === providerName) ?? (providerName ? undefined : providers.find((p) => p.is_default));
  if (provider?.type === "opencode-go") return [];
  const entry = providerModels.find((p) => p.provider.name === provider?.name)?.models.find((m) => m.id === model);
  return entry?.reasoning_efforts ?? legacyEfforts;
}

export function effectiveEffort(selected: string, options: string[]): string {
  return options.includes(selected) ? selected : options.includes("medium") ? "medium" : options[0] ?? "";
}

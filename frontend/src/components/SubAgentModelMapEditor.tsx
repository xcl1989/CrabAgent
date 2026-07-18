/**
 * Editor for the sub-agent model map (cost control).
 *
 * Maps a parent agent's "provider|model" to a child agent's "provider|model",
 * so that when a parent agent using model X delegates a sub-task, the child
 * automatically switches to the mapped (usually cheaper) model — possibly on
 * a different provider.
 */

import { useTranslation } from "react-i18next";
import { Plus, X } from "lucide-react";
import ModelSelector from "./ModelSelector";
import type { ProviderModels } from "../hooks/useModelSelector";
import { Button } from "./ui";

export interface ModelMapRow {
  parentProvider: string;
  parentModel: string;
  childProvider: string;
  childModel: string;
}

/** Parse the stored JSON ``{"P|M": "P'|M'"}`` into editable rows. */
export function parseModelMap(raw: string): ModelMapRow[] {
  if (!raw) return [];
  try {
    const obj = JSON.parse(raw);
    if (typeof obj !== "object" || obj === null) return [];
    return Object.entries(obj)
      .map(([key, val]) => {
        const [pp, pm] = key.split("|", 2);
        const [cp, cm] = String(val).split("|", 2);
        return {
          parentProvider: pp || "",
          parentModel: pm || "",
          childProvider: cp || "",
          childModel: cm || "",
        };
      })
      .filter((r) => r.parentModel && r.childModel);
  } catch {
    return [];
  }
}

/** Serialize rows back into the stored JSON string. */
export function serializeModelMap(rows: ModelMapRow[]): string {
  const obj: Record<string, string> = {};
  for (const r of rows) {
    if (!r.parentModel || !r.childModel) continue;
    obj[`${r.parentProvider}|${r.parentModel}`] = `${r.childProvider}|${r.childModel}`;
  }
  return JSON.stringify(obj);
}

interface Props {
  rows: ModelMapRow[];
  onChange: (rows: ModelMapRow[]) => void;
  providerModels: ProviderModels[];
}

export function SubAgentModelMapEditor({ rows, onChange, providerModels }: Props) {
  const { t } = useTranslation();

  const updateRow = (idx: number, patch: Partial<ModelMapRow>) => {
    onChange(rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  };

  const addRow = () => {
    onChange([
      ...rows,
      { parentProvider: "", parentModel: "", childProvider: "", childModel: "" },
    ]);
  };

  const removeRow = (idx: number) => {
    onChange(rows.filter((_, i) => i !== idx));
  };

  return (
    <div className="flex flex-col gap-2">
      {rows.length === 0 && (
        <p className="text-xs text-[var(--text-tertiary)] italic">
          {t("settingsPage.subAgentMapEmpty")}
        </p>
      )}
      {rows.map((row, idx) => (
        <div key={idx} className="flex items-center gap-1.5">
          <div className="flex-1 min-w-0">
            <ModelSelector
              providerModels={providerModels}
              selectedModel={row.parentModel}
              selectedProvider={row.parentProvider || undefined}
              onChange={(modelId, providerName) =>
                updateRow(idx, { parentModel: modelId, parentProvider: providerName })
              }
              dropdownUpward={false}
            />
          </div>
          <span className="text-[var(--text-tertiary)] text-sm shrink-0">→</span>
          <div className="flex-1 min-w-0">
            <ModelSelector
              providerModels={providerModels}
              selectedModel={row.childModel}
              selectedProvider={row.childProvider || undefined}
              onChange={(modelId, providerName) =>
                updateRow(idx, { childModel: modelId, childProvider: providerName })
              }
              dropdownUpward={false}
            />
          </div>
          <button
            type="button"
            onClick={() => removeRow(idx)}
            className="shrink-0 p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--danger)] hover:bg-[var(--danger)]/10 transition-colors"
            title={t("common.delete")}
          >
            <X size={14} />
          </button>
        </div>
      ))}
      <Button variant="secondary" size="sm" onClick={addRow} className="self-start mt-1">
        <Plus size={14} />
        {t("settingsPage.subAgentMapAdd")}
      </Button>
    </div>
  );
}

import { useState } from "react";
import { Provider, CatalogEntry } from "../api/providers";
import * as providersApi from "../api/providers";

interface Props {
  providers: Provider[];
  catalog: CatalogEntry[];
  onClose: () => void;
  onRefresh: () => void;
}

export default function ProviderPanel({ providers, catalog, onClose, onRefresh }: Props) {
  const [mode, setMode] = useState<"list" | "add">("list");
  const [formType, setFormType] = useState(catalog[0]?.type || "");
  const [formName, setFormName] = useState("");
  const [formKey, setFormKey] = useState("");
  const [error, setError] = useState<string | null>(null);

  const handleAdd = async () => {
    setError(null);
    if (!formName || !formKey || !formType) {
      setError("All fields required");
      return;
    }
    try {
      await providersApi.createProvider({ name: formName, type: formType, api_key: formKey });
      onRefresh();
      setMode("list");
      setFormName("");
      setFormKey("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed");
    }
  };

  const handleSetDefault = async (name: string) => {
    await providersApi.updateProvider(name, { is_default: true });
    onRefresh();
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete provider "${name}"?`)) return;
    await providersApi.deleteProvider(name);
    onRefresh();
  };

  const selectedCatalog = catalog.find((c) => c.type === formType);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.6)" }}>
      <div className="w-full max-w-md rounded-xl p-6 max-h-[80vh] overflow-y-auto" style={{ background: "var(--bg-secondary)" }}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Providers</h2>
          <button onClick={onClose} className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Close
          </button>
        </div>

        {mode === "list" ? (
          <>
            {providers.map((p) => (
              <div
                key={p.name}
                className="p-3 mb-2 rounded-lg flex items-center justify-between"
                style={{ background: "var(--bg-tertiary)" }}
              >
                <div>
                  <div className="text-sm font-medium">
                    {p.display_name} {p.is_default && <span className="text-xs text-blue-400">default</span>}
                  </div>
                  <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
                    {p.type} | {p.api_key_preview}
                  </div>
                </div>
                <div className="flex gap-2">
                  {!p.is_default && (
                    <button
                      onClick={() => handleSetDefault(p.name)}
                      className="text-xs px-2 py-1 rounded"
                      style={{ background: "var(--bg-primary)", color: "var(--text-secondary)" }}
                    >
                      Set default
                    </button>
                  )}
                  <button
                    onClick={() => handleDelete(p.name)}
                    className="text-xs px-2 py-1 rounded"
                    style={{ color: "var(--danger)" }}
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
            <button
              onClick={() => setMode("add")}
              className="w-full mt-2 py-2 rounded-lg text-sm font-medium"
              style={{ background: "var(--accent)", color: "#fff" }}
            >
              + Add Provider
            </button>
          </>
        ) : (
          <>
            {error && <p className="text-sm mb-3" style={{ color: "var(--danger)" }}>{error}</p>}

            <div className="mb-3">
              <label className="text-xs block mb-1" style={{ color: "var(--text-secondary)" }}>Type</label>
              <select
                value={formType}
                onChange={(e) => setFormType(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              >
                {catalog.map((c) => (
                  <option key={c.type} value={c.type}>{c.display_name}</option>
                ))}
              </select>
            </div>

            <div className="mb-3">
              <label className="text-xs block mb-1" style={{ color: "var(--text-secondary)" }}>Name</label>
              <input
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="my-provider"
                className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              />
            </div>

            {selectedCatalog && (
              <div className="mb-3 text-xs" style={{ color: "var(--text-secondary)" }}>
                Base URL: {selectedCatalog.base_url}
              </div>
            )}

            <div className="mb-4">
              <label className="text-xs block mb-1" style={{ color: "var(--text-secondary)" }}>API Key</label>
              <input
                type="password"
                value={formKey}
                onChange={(e) => setFormKey(e.target.value)}
                placeholder="sk-..."
                className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              />
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => setMode("list")}
                className="flex-1 py-2 rounded-lg text-sm"
                style={{ background: "var(--bg-tertiary)", color: "var(--text-secondary)" }}
              >
                Cancel
              </button>
              <button
                onClick={handleAdd}
                className="flex-1 py-2 rounded-lg text-sm font-medium"
                style={{ background: "var(--accent)", color: "#fff" }}
              >
                Add
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

import { useState, useEffect } from "react";
import { Molt, MoltDiff, listMolts, getMoltDiff, rollbackMolt } from "../api/sessions";
import { formatTimeShort } from "../api/time";

interface Props {
  sessionId: string;
}

export default function MoltTimeline({ sessionId }: Props) {
  const [molts, setMolts] = useState<Molt[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [diffData, setDiffData] = useState<MoltDiff[] | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);

  useEffect(() => {
    if (!sessionId) return;
    setLoading(true);
    listMolts(sessionId).then(setMolts).catch(() => setMolts([])).finally(() => setLoading(false));
  }, [sessionId]);

  const handleToggle = async (moltId: string) => {
    if (expandedId === moltId) {
      setExpandedId(null);
      setDiffData(null);
      return;
    }
    setExpandedId(moltId);
    setDiffLoading(true);
    try {
      const result = await getMoltDiff(sessionId, moltId);
      setDiffData(result.diffs);
    } catch {
      setDiffData([]);
    }
    setDiffLoading(false);
  };

  const handleRollback = async (moltId: string) => {
    if (!confirm(`Rollback to ${moltId}?`)) return;
    try {
      const result = await rollbackMolt(sessionId, moltId);
      alert(`Rolled back: ${result.restored} files`);
    } catch (e) {
      alert("Rollback failed");
    }
  };

  if (molts.length === 0) {
    if (loading) return null;
    return null;
  }

  return (
    <div className="border-t" style={{ borderTop: "1px solid var(--border)" }}>
      <div className="p-2 text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>Molts</div>
      {molts.slice(0, 10).map((m) => (
        <div key={m.molt_id}>
          <div
            onClick={() => handleToggle(m.molt_id)}
            className="flex items-center justify-between px-2 py-1 cursor-pointer text-xs hover:opacity-80"
            style={{ color: "var(--text-primary)" }}
          >
            <div className="flex items-center gap-1 min-w-0">
              <span style={{ color: "#fbbf24" }}>🦀</span>
              <span className="truncate">{m.description}</span>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <span style={{ color: "var(--text-secondary)", fontSize: 10 }}>
                {formatTimeShort(m.created_at)}
              </span>
              <button
                onClick={(e) => { e.stopPropagation(); handleRollback(m.molt_id); }}
                className="text-[10px] px-1 rounded"
                style={{ background: "var(--bg-tertiary)", color: "var(--text-secondary)" }}
              >
                ↩
              </button>
            </div>
          </div>
          {expandedId === m.molt_id && (
            <div className="px-3 pb-2" style={{ background: "var(--bg-tertiary)" }}>
              {diffLoading ? (
                <div className="text-xs" style={{ color: "var(--text-secondary)" }}>Loading...</div>
              ) : diffData && diffData.length > 0 ? (
                diffData.map((d) => (
                  <div key={d.file} className="mb-1">
                    <div className="text-[10px] font-medium mt-1" style={{ color: "var(--accent)" }}>{d.file}</div>
                    <pre className="text-[10px] leading-tight whitespace-pre-wrap max-h-24 overflow-y-auto rounded p-1" style={{ color: "var(--text-primary)", background: "var(--bg-secondary)" }}>
                      {d.diff.slice(0, 1000)}
                    </pre>
                  </div>
                ))
              ) : (
                <div className="text-xs" style={{ color: "var(--text-secondary)" }}>No changes</div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

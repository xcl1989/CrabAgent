import { useState, useEffect } from "react";
import * as sessionsApi from "../api/sessions";
import { BranchInfo } from "../api/sessions";

interface Props {
  sessionId: string;
  activeBranch: string;
  onSwitch: (branchId: string) => void;
  onReplay?: (branchId: string) => void;
}

export default function BranchSelector({ sessionId, activeBranch, onSwitch, onReplay }: Props) {
  const [branches, setBranches] = useState<BranchInfo[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    sessionsApi.listBranches(sessionId).then(setBranches).catch(() => {});
  }, [sessionId, activeBranch]);

  if (branches.length <= 1) return null;

  return (
    <div className="relative px-4 py-1.5 flex items-center gap-2" style={{ borderBottom: "1px solid var(--border)" }}>
      <span className="text-xs" style={{ color: "var(--text-secondary)" }}>Branch:</span>
      <button
        onClick={() => setOpen(!open)}
        className="text-xs px-2 py-1 rounded flex items-center gap-1"
        style={{
          background: "var(--bg-secondary)",
          color: "var(--text-primary)",
          border: "1px solid var(--border)",
        }}
      >
        <span style={{ color: activeBranch === "main" ? "#67e8f9" : "#fbbf24" }}>⎇</span>
        {activeBranch}
        <span style={{ color: "var(--text-secondary)", fontSize: "10px" }}>▼</span>
      </button>

      {open && (
        <div
          className="absolute top-full left-16 z-50 py-1 rounded shadow-lg min-w-[160px]"
          style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}
        >
          {branches.map((b) => (
            <div key={b.branch_id} className="flex items-center">
              <button
                onClick={() => {
                  onSwitch(b.branch_id);
                  setOpen(false);
                }}
                className="flex-1 text-left px-3 py-1.5 text-xs flex items-center gap-2"
                style={{
                  color: b.branch_id === activeBranch ? "#67e8f9" : "var(--text-primary)",
                  background: b.branch_id === activeBranch ? "var(--bg-tertiary)" : "transparent",
                }}
              >
                <span style={{ color: b.branch_id === "main" ? "#67e8f9" : "#fbbf24" }}>⎇</span>
                <span>{b.branch_id}</span>
                <span style={{ color: "var(--text-secondary)" }}>({b.message_count} msgs)</span>
              </button>
              {onReplay && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onReplay(b.branch_id);
                    setOpen(false);
                  }}
                  className="text-xs px-2 py-1.5 hover:opacity-80"
                  style={{ color: "#34d399" }}
                  title="Replay this branch"
                >
                  ▶
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

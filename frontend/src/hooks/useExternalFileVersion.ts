import { useEffect, useState } from "react";
import { getFileVersion } from "../api/files";

/** Observe external edits without claiming to prevent races or replace save-time checks. */
export function useExternalFileVersion(path: string | null, version: string, absolute = false) {
  const [changed, setChanged] = useState(false);
  useEffect(() => {
    setChanged(false);
    if (!path || !version) return;
    let active = true;
    let checking = false;
    const check = async () => {
      if (checking || document.visibilityState === "hidden") return;
      checking = true;
      try {
        const current = await getFileVersion(path, absolute);
        if (active) setChanged(current !== version);
      } catch {
        // A failed check is not evidence that the file is unchanged.
      } finally {
        checking = false;
      }
    };
    const timer = window.setInterval(check, 5000);
    window.addEventListener("focus", check);
    return () => { active = false; window.clearInterval(timer); window.removeEventListener("focus", check); };
  }, [path, version, absolute]);
  return changed;
}

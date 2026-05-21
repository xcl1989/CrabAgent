from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


async def rollback(molt_id: str, workspace: Path, files_only: bool = False) -> list[str]:
    md = workspace / ".crabagent" / "molts" / molt_id
    if not md.exists():
        return [f"Snapshot {molt_id} not found"]

    diff_path = md / "diff.txt"
    is_git = (workspace / ".git").exists()
    restored: list[str] = []

    if is_git and diff_path.exists():
        try:
            for f in sorted(md.rglob("*")):
                if f.is_file() and f.name != "diff.txt":
                    rel = f.relative_to(md)
                    target = workspace / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(f), str(target))
                    restored.append(str(rel))
        except Exception as e:
            logger.warning("git checkout failed, falling back to file copy: %s", e)
            restored = []

    if not restored:
        for f in sorted(md.rglob("*")):
            if f.is_file() and f.name != "diff.txt":
                rel = f.relative_to(md)
                target = workspace / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(f), str(target))
                restored.append(str(rel))

    return restored

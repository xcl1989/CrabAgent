from __future__ import annotations

import logging
import shutil

from crabagent.core.config import settings

logger = logging.getLogger(__name__)

_next_seq: int = 0


def _molt_id() -> str:
    global _next_seq
    _next_seq += 1
    return f"molt_{_next_seq:04d}"


async def take_snapshot(context, filepaths: list[str], description: str = "") -> dict | None:
    workspace = context.workspace.resolve()
    mid = _molt_id()
    md = settings.workspace.resolve() / ".crabagent" / "molts" / mid
    md.mkdir(parents=True, exist_ok=True)

    is_git = (workspace / ".git").exists()
    saved_files: list[str] = []
    method = "copy"

    if is_git:
        try:
            diff_lines: list[str] = []
            for fp in filepaths:
                target = workspace / fp
                if not target.exists():
                    continue
                import subprocess
                result = subprocess.run(
                    ["git", "diff", "--", fp],
                    capture_output=True, text=True, cwd=str(workspace), timeout=10,
                )
                if result.stdout.strip():
                    diff_lines.append(f"--- {fp}\n{result.stdout}")

            if diff_lines:
                method = "git"
                # store diff
                diff_path = md / "diff.txt"
                diff_path.write_text("\n".join(diff_lines), encoding="utf-8")
                # also store file copies for reliable rollback
                for fp in filepaths:
                    target = workspace / fp
                    if target.exists():
                        dst = md / fp
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(target), str(dst))
                        saved_files.append(fp)
        except Exception as e:
            logger.warning("git diff failed, falling back to copy: %s", e)
            method = "copy"

    if method == "copy":
        for fp in filepaths:
            target = workspace / fp
            if target.exists():
                dst = md / fp
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(target), str(dst))
                saved_files.append(fp)

    if not saved_files:
        shutil.rmtree(str(md), ignore_errors=True)
        return None

    return {
        "molt_id": mid,
        "description": description or f"Before: {', '.join(saved_files)}",
        "method": method,
        "files": saved_files,
        "snapshot_dir": str(md),
    }

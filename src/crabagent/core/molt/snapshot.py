from __future__ import annotations

import asyncio
import logging
import shutil

logger = logging.getLogger(__name__)

import time as _time


def _molt_id() -> str:
    """Return a unique molt ID using timestamp + counter to survive server restarts."""
    global _next_seq
    _next_seq += 1
    ts = _time.time_ns() // 1000  # microseconds
    return f"molt_{ts}_{_next_seq:04d}"


async def take_snapshot(context, filepaths: list[str], description: str = "") -> dict | None:
    workspace = context.workspace.resolve()
    mid = _molt_id()
    md = workspace / ".crabagent" / "molts" / mid
    try:
        md.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("Cannot create molt directory %s (read-only filesystem)", md)
        return None

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

                proc = await asyncio.create_subprocess_exec(
                    "git",
                    "diff",
                    "--",
                    fp,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(workspace),
                )
                try:
                    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
                    if stdout and stdout.strip():
                        diff_lines.append(f"--- {fp}\n{stdout.decode('utf-8', errors='replace')}")
                except TimeoutError:
                    proc.kill()

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

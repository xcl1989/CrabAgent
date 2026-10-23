"""Create a verified compact DB snapshot, never modify the live source.

Usage: python3 scripts/compact_message_db.py --source ~/.crabagent/crabagent.db \
    --output ~/.crabagent/backups/crabagent.compact.db

Stop the application before swapping databases. An online snapshot does not
contain messages written after the snapshot; do NOT swap it into a running app.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path


def compact_snapshot(source: Path, output: Path, timeout: float = 300) -> dict:
    source = source.expanduser().resolve(strict=True)
    output = output.expanduser().resolve()
    if source == output:
        raise ValueError("Output must not be the source database")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects existing backups, including the source.
    with output.open("xb"):
        pass
    deadline = time.monotonic() + timeout

    def check_deadline(*_args):
        if time.monotonic() > deadline:
            raise TimeoutError("Snapshot timed out; source database is unchanged")

    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(output)) as dst:
                src.backup(dst, pages=256, progress=check_deadline, sleep=0.05)
                before = output.stat().st_size
                counts = dict(
                    dst.execute(
                        "SELECT 'messages', count(*) FROM messages UNION ALL "
                        "SELECT 'conversations', count(*) FROM conversations"
                    )
                )
                cjk_count = dst.execute("SELECT count(*) FROM messages_fts_cjk").fetchone()[0]
                for trigger in ("messages_ai", "messages_ad", "messages_au"):
                    dst.execute(f"DROP TRIGGER IF EXISTS {trigger}")
                dst.execute("DROP TABLE IF EXISTS messages_fts")
                dst.commit()
                dst.execute("VACUUM")
                check = dst.execute("PRAGMA integrity_check").fetchall()
                if check != [("ok",)]:
                    raise RuntimeError(f"Snapshot integrity check failed: {check[:5]}")
                for table, count in counts.items():
                    if dst.execute(f"SELECT count(*) FROM {table}").fetchone()[0] != count:
                        raise RuntimeError(f"Row count changed: {table}")
                if dst.execute("SELECT count(*) FROM messages_fts_cjk").fetchone()[0] != cjk_count:
                    raise RuntimeError("CJK search index row count changed")
        return {
            "source": str(source),
            "output": str(output),
            "snapshot_bytes": before,
            "compact_bytes": output.stat().st_size,
            "saved_bytes": before - output.stat().st_size,
            "rows": counts,
            "cjk_rows": cjk_count,
            "integrity_check": "ok",
            "source_modified": False,
        }
    except BaseException:
        # Never leave a partially verified output that could be mistaken for a backup.
        output.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(compact_snapshot(args.source, args.output), indent=2))

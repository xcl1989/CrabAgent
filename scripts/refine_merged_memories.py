"""Refine memories whose content was folded from several duplicates.

The key migration collapses same-subject rows, but folding appends paragraphs,
which leaves near-identical sentences stacked on top of each other. This asks
the model for one tight paragraph that keeps every distinct fact.

Only touches rows whose ``evidence`` contains ``merged-from:``, i.e. produced by
the migration, so hand-written memories are never rewritten.

Usage::

    python3 scripts/refine_merged_memories.py --user-id 1 --model glm-5.3-flash
    python3 scripts/refine_merged_memories.py --user-id 1 --model glm-5.3-flash --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import litellm  # noqa: E402

SYSTEM = (
    "You compress redundant notes. The input contains several paragraphs that "
    "describe the SAME lesson from slightly different angles, produced by "
    "repeated automatic extraction.\n\n"
    "Produce ONE paragraph that:\n"
    "- keeps every distinct fact, example, command, path and constraint;\n"
    "- removes sentences that only restate another one;\n"
    "- uses the language of the majority of the input;\n"
    "- stays under 600 characters if the distinct facts allow it.\n\n"
    "Reply with the paragraph only. No preamble, no bullets, no quotes."
)


def db_path() -> Path:
    return Path(os.path.expanduser("~/.crabagent/crabagent.db"))


async def refine(text: str, model: str, params: dict) -> str:
    response = await litellm.acompletion(
        model=model,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": text[:6000]}],
        # Reasoning models burn the budget on reasoning_content first.
        max_tokens=3000,
        temperature=0.1,
        **params,
    )
    return (response.choices[0].message.content or "").strip()


async def run(user_id: int, model: str, apply: bool, min_len: int) -> int:
    from crabagent.core.agent.reflect import _resolve_llm_params

    params = await _resolve_llm_params(None)
    if params is None:
        print("no provider configured")
        return 2

    conn = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT id, key, content FROM agent_memory "
        "WHERE user_id = ? AND evidence LIKE 'merged-from:%' AND length(content) >= ? "
        "ORDER BY length(content) DESC",
        (user_id, min_len),
    ).fetchall()
    conn.close()
    print(f"{len(rows)} rows to refine (>= {min_len} chars)")

    results: dict[int, str] = {}
    for rid, key, content in rows:
        try:
            refined = await refine(content, model, params)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{rid}] failed: {exc}")
            continue
        if not refined or len(refined) >= len(content):
            print(f"  [{rid}] kept original ({len(content)} chars)")
            continue
        print(f"  [{rid}] {len(content)} -> {len(refined)} chars  {key}")
        results[rid] = refined

    out = Path("/tmp/refined-memories.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"proposal written to {out} ({len(results)} rows)")

    if not apply or not results:
        print("Dry run. Re-run with --apply to write.")
        return 0

    backup = db_path().with_suffix(f".backup-{datetime.now():%Y%m%d-%H%M%S}.db")
    src = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
    dst = sqlite3.connect(backup)
    src.backup(dst)
    dst.close()
    src.close()
    print(f"backup: {backup}")

    db = sqlite3.connect(db_path(), timeout=30)
    db.execute("BEGIN IMMEDIATE")
    changed = 0
    for rid, refined in results.items():
        cur = db.execute(
            "UPDATE agent_memory SET content = ?, "
            "evidence = COALESCE(evidence,'') || ' | refined' WHERE id = ? AND user_id = ?",
            (refined, rid, user_id),
        )
        changed += cur.rowcount
    db.execute("DELETE FROM memory_embedding WHERE memory_id IN ("
               + ",".join(str(r) for r in results) + ")")
    db.commit()
    print(f"refined {changed} rows")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-id", type=int, required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--min-len", type=int, default=250)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    return asyncio.run(run(args.user_id, args.model, args.apply, args.min_len))


if __name__ == "__main__":
    raise SystemExit(main())

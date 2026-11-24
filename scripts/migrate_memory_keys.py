"""Migrate legacy memory keys to the semantic scheme (see MEMORY-KEYS.md).

    user_pref:<topic>:<hash>   ->  user_pref:<slug>
    lesson:<agent>:llm:<hash>  ->  lesson:<agent>:<slug>

Dry run by default; prints the mapping and every collision. ``--apply`` writes
an archive file first, then renames inside one transaction.

Usage::

    python3 scripts/migrate_memory_keys.py --user-id 1            # dry run
    python3 scripts/migrate_memory_keys.py --user-id 1 --apply
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from crabagent.core.agent.preference_schema import (  # noqa: E402
    GENERIC_SLUGS,
    normalize_slug,
)

PREF_HASH = re.compile(r"^user_pref:(?P<topic>[^:]+):(?P<hash>[0-9a-f]{8,})$")
DUPLICATE_THRESHOLD = 0.85
LESSON_HASH = re.compile(r"^lesson:(?P<agent>[^:]+):llm:(?P<hash>[0-9a-f]{8,})$")


def db_path() -> Path:
    return Path(os.path.expanduser("~/.crabagent/crabagent.db"))


def usable_slug(raw: str) -> str:
    slug = normalize_slug(raw)
    if len(slug) < 3 or slug in GENERIC_SLUGS:
        return ""
    return slug


def plan(conn: sqlite3.Connection, user_id: int) -> tuple[list[dict], list[dict]]:
    """Return (renames, needs_slug).

    ``renames`` already carry the target key. ``needs_slug`` lists rows whose
    legacy topic is not usable as a slug; they need a model-generated one.
    """
    renames: list[dict] = []
    needs_slug: list[dict] = []
    rows = conn.execute(
        "SELECT id, key, memory_type, agent_name, content, category, scope, "
        "workspace_path, importance, access_count FROM agent_memory WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    for row in rows:
        (rid, key, mtype, agent, content, category, scope, ws, imp, acc) = row
        m = PREF_HASH.match(key)
        if m and mtype == "user_preference":
            slug = usable_slug(m.group("topic"))
            item = {"id": rid, "old": key, "memory_type": mtype, "agent": agent,
                    "content": content, "category": category, "importance": imp, "access": acc,
                    "scope": scope, "workspace_path": ws}
            if slug:
                renames.append({**item, "new": f"user_pref:{slug}", "slug": slug})
            else:
                needs_slug.append({**item, "new": None, "reason": f"generic topic {m.group('topic')!r}"})
            continue
        m = LESSON_HASH.match(key)
        if m and mtype == "agent_lesson":
            needs_slug.append({
                "id": rid, "old": key, "memory_type": mtype, "agent": agent,
                "content": content, "category": category, "importance": imp, "access": acc,
                "scope": scope, "workspace_path": ws, "new": None, "reason": "lesson hash key",
            })
    return renames, needs_slug


def _keeper_key(item: dict) -> tuple:
    """Most informative row wins: importance, then content length, then newest."""
    return (item["importance"] or 0, len(item["content"] or ""), item["id"])


def find_collisions(renames: list[dict]) -> list[dict]:
    """Group renames landing on the same identity tuple.

    Identity mirrors ``agent_memory_upsert``: same tuple means the second write
    would overwrite the first, so the rows must be folded explicitly.
    """
    by_target: dict[tuple, list[dict]] = defaultdict(list)
    for item in renames:
        by_target[(item["memory_type"], item["agent"] or "", item["scope"] or "",
                   item["workspace_path"] or "", item["new"])].append(item)
    groups = []
    for (_mtype, _agent, _scope, _ws, key), items in by_target.items():
        if len(items) > 1:
            ordered = sorted(items, key=_keeper_key, reverse=True)
            groups.append({"key": key, "keeper": ordered[0], "absorbed": ordered[1:]})
    return groups


def merge_contents(keeper: dict, absorbed: list[dict]) -> tuple[str, list[str]]:
    """Fold absorbed rows into the keeper's content.

    Near-identical duplicates are dropped rather than appended: the whole point
    of the migration is to collapse the same sentence rephrased eight times.
    Returns (new_content, dropped_keys).
    """
    from crabagent.core.agent.lesson_dedup import string_similarity_score

    content = (keeper["content"] or "").strip()
    dropped: list[str] = []
    for item in absorbed:
        other = (item["content"] or "").strip()
        if not other:
            continue
        score = string_similarity_score(content.lower(), other.lower())
        if score >= DUPLICATE_THRESHOLD or other.lower() in content.lower():
            dropped.append(item["old"])
            continue
        content = f"{content}\n\n{other}"
    return content, dropped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-id", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--slugs", type=Path, default=None,
                    help="JSON mapping of memory id -> slug from generate_memory_slugs.py")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    renames, needs_slug = plan(conn, args.user_id)
    conn.close()

    generated: dict[str, str] = {}
    if args.slugs and args.slugs.exists():
        generated = json.loads(args.slugs.read_text(encoding="utf-8"))

    # Fold generated slugs into the rename plan; anything still without one is
    # reported and blocks --apply.
    remaining = []
    for item in needs_slug:
        slug = usable_slug(generated.get(str(item["id"]), ""))
        if not slug:
            remaining.append(item)
            continue
        if item["memory_type"] == "agent_lesson":
            target = f"lesson:{item['agent'] or 'default'}:{slug}"
        else:
            target = f"user_pref:{slug}"
        renames.append({**item, "new": target, "slug": slug})
    needs_slug = remaining

    print(f"user {args.user_id}: {len(renames)} renamable, {len(needs_slug)} need a slug")
    print("\n--- renames (first 20) ---")
    for item in renames[:20]:
        print(f"  {item['old']}\n    -> {item['new']}")
    if len(renames) > 20:
        print(f"  ... {len(renames) - 20} more")

    if needs_slug:
        print(f"\n--- need a model-generated slug ({len(needs_slug)}) ---")
        for item in needs_slug[:10]:
            print(f"  [{item['id']}] {item['old']}  ({item['reason']})")
            print(f"      {item['content'][:90]}")
        if len(needs_slug) > 10:
            print(f"  ... {len(needs_slug) - 10} more")

    collisions = find_collisions(renames)
    if collisions:
        print(f"\n--- collisions ({len(collisions)} groups) ---")
        for group in collisions:
            rows = [group["keeper"], *group["absorbed"]]
            print(f"  {group['key']} <- {len(rows)} rows "
                  f"(keeper [{group['keeper']['id']}])")
            for item in rows:
                print(f"      [{item['id']}] imp={item['importance']} "
                      f"len={len(item['content'] or '')} acc={item['access']}")

    if not args.apply:
        print("\nDry run. Re-run with --apply to write (archive is created first).")
        return 0

    if needs_slug:
        print("\nRefusing to apply: rows still need model-generated slugs. "
              "Migrate those first (see --emit-needs-slug).")
        return 2

    backup = db_path().with_suffix(f".backup-{datetime.now():%Y%m%d-%H%M%S}.db")
    src = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
    dst = sqlite3.connect(backup)
    src.backup(dst)
    dst.close()
    src.close()
    print(f"\nbackup: {backup}")

    archive_dir = Path.home() / ".crabagent" / "memory-archives"
    archive_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, archive = tempfile.mkstemp(prefix=f"user-{args.user_id}-keymigration-", suffix=".json", dir=archive_dir)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "user_id": args.user_id,
                   "reason": "key migration to semantic scheme",
                   "mappings": [{"id": i["id"], "old": i["old"], "new": i["new"]} for i in renames]},
                  fh, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())
    print(f"archive: {archive}")

    db = sqlite3.connect(db_path(), timeout=30)
    db.execute("BEGIN IMMEDIATE")
    changed = 0
    collision_ids = {item["id"] for group in collisions for item in [group["keeper"], *group["absorbed"]]}
    for item in renames:
        if item["id"] in collision_ids:
            continue  # handled below
        cur = db.execute(
            "UPDATE agent_memory SET key = ? WHERE id = ? AND user_id = ? AND key = ?",
            (item["new"], item["id"], args.user_id, item["old"]),
        )
        changed += cur.rowcount

    merged_rows = 0
    for group in collisions:
        keeper = group["keeper"]
        new_content, dropped = merge_contents(keeper, group["absorbed"])
        folded = [a for a in group["absorbed"] if a["old"] not in dropped]
        provenance = ", ".join(f"merged-from:{a['old']}" for a in group["absorbed"])
        db.execute(
            "UPDATE agent_memory SET key = ?, content = ?, evidence = CASE "
            "WHEN COALESCE(evidence,'') = '' THEN ? ELSE evidence || ' | ' || ? END "
            "WHERE id = ? AND user_id = ?",
            (group["key"], new_content, provenance, provenance, keeper["id"], args.user_id),
        )
        changed += 1
        drop_ids = [a["id"] for a in group["absorbed"]]
        db.execute(f"DELETE FROM memory_embedding WHERE memory_id IN ({','.join(map(str, drop_ids))})")
        db.execute(f"DELETE FROM conversation_memory_injections WHERE memory_uid IN "
                   f"(SELECT memory_uid FROM agent_memory WHERE id IN ({','.join(map(str, drop_ids))}))")
        db.execute(f"DELETE FROM agent_memory WHERE id IN ({','.join(map(str, drop_ids))}) AND user_id = ?",
                   (args.user_id,))
        merged_rows += len(drop_ids)
        print(f"  {group['key']}: kept [{keeper['id']}], absorbed {len(drop_ids)}, "
              f"dropped-as-duplicate {len(dropped)}, appended {len(folded)}")
    db.commit()
    print(f"renamed {changed} rows, folded {merged_rows} duplicates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

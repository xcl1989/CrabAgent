"""Consolidate agent lessons: merge same-subject fragments, keep distinct facts.

209 lessons for one agent is far past the point of usefulness (at most four are
recalled per turn). This folds them in batches: the model merges near-synonyms
and keeps one entry per subject, dropping entries that only restate a rule the
batch already covers.

Every original row is archived before anything is deleted.

Usage::

    python3 scripts/consolidate_lessons.py --user-id 1 --agent coder --model glm-5.3-flash
    python3 scripts/consolidate_lessons.py --user-id 1 --agent coder --model glm-5.3-flash --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import litellm  # noqa: E402

BATCH = 10
TARGET_PER_BATCH = 6
# Preferences are mostly distinct subjects, so compression is gentler.
PREF_TARGET = 5

PREF_SYSTEM = (
    "You consolidate a user-preference list recorded by an automatic reflection "
    "pipeline. Problems: several entries restate the same preference, and some are "
    "not preferences at all but one-off task facts (a specific file path that was "
    "corrected once, a single command that was run once).\n\n"
    "Rewrite the batch as the preferences it actually contains:\n"
    "- merge entries that express the same preference;\n"
    "- DROP entries that only record what happened in one task rather than what the "
    "user wants in general;\n"
    "- keep each remaining preference as one sentence stating what the USER wants;\n"
    "- keep concrete details only when they define the preference (a package name, a "
    "required flag), not when they merely describe the incident;\n"
    "- use the language of the majority of the input;\n"
    "- it is fine to output fewer entries, but never invent one.\n\n"
    "Reply with one block per preference, blank line between blocks, using exactly:\n"
    "Slug: <2-4 lowercase English words joined by hyphens naming the subject>\n"
    "Content: <one sentence>\n\n"
    "No preamble, no numbering, no markdown."
)

SYSTEM = (
    "You consolidate engineering lessons. The input lists lessons recorded by an "
    "automatic reflection pipeline; many restate the same rule in different words "
    "and many are so narrow they describe one incident.\n\n"
    f"Rewrite the batch as at most {TARGET_PER_BATCH} lessons that:\n"
    "- each cover ONE subject, stated as a general rule;\n"
    "- keep every concrete detail that makes a rule actionable: commands, file "
    "paths, flags, error strings, numeric thresholds;\n"
    "- merge entries that say the same thing; drop an entry only when another "
    "entry already captures it;\n"
    "- do not invent advice that is not in the input;\n"
    "- use the language of the majority of the input.\n\n"
    "Reply with one block per lesson, blank line between blocks, using exactly:\n"
    "Slug: <2-4 lowercase English words joined by hyphens naming the subject>\n"
    "Content: <one to three sentences>\n\n"
    "No preamble, no numbering, no markdown."
)


def db_path() -> Path:
    return Path(os.path.expanduser("~/.crabagent/crabagent.db"))


def parse(text: str) -> list[dict]:
    out: list[dict] = []
    for block in (b.strip() for b in text.split("\n\n")):
        if not block:
            continue
        slug = content = ""
        for line in block.splitlines():
            if ":" not in line:
                continue
            label, value = line.split(":", 1)
            label = label.strip().lower()
            if label == "slug":
                slug = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower()).strip("-")
            elif label in ("content", "lesson", "内容"):
                content = value.strip()
        if slug and content and len(content) >= 20:
            out.append({"slug": slug, "content": content})
    return out


async def run(user_id: int, agent: str, model: str, apply: bool, mtype: str = "agent_lesson") -> int:
    from crabagent.core.agent.reflect import _resolve_llm_params

    params = await _resolve_llm_params(None)
    if params is None:
        print("no provider configured")
        return 2

    conn = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
    if mtype == "user_preference":
        rows = conn.execute(
            "SELECT id, key, content, importance, access_count, task_category, category "
            "FROM agent_memory WHERE user_id = ? AND memory_type = 'user_preference' "
            "ORDER BY length(content) DESC, id",
            (user_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, key, content, importance, access_count, task_category, category "
            "FROM agent_memory WHERE user_id = ? AND memory_type = 'agent_lesson' "
            "AND agent_name = ? ORDER BY access_count DESC, importance DESC, id",
            (user_id, agent),
        ).fetchall()
    conn.close()
    system = PREF_SYSTEM if mtype == "user_preference" else SYSTEM
    per_batch = PREF_TARGET if mtype == "user_preference" else TARGET_PER_BATCH
    print(f"{len(rows)} x {mtype}; batch={BATCH}, target<={per_batch}")

    merged: list[dict] = []
    for start in range(0, len(rows), BATCH):
        batch = rows[start:start + BATCH]
        listing = "\n\n".join(f"[{r[0]}] {r[2]}" for r in batch)
        for attempt in range(3):
            try:
                response = await litellm.acompletion(
                    model=model,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": listing[:12000]}],
                    # Reasoning models spend this budget on reasoning_content
                    # first; 25-item batches exhausted 4000 and returned an
                    # empty body with finish_reason=length.
                    max_tokens=6000,
                    temperature=0.1,
                    **params,
                )
                got = parse(response.choices[0].message.content or "")
                if not got:
                    raise ValueError("empty parse")
                break
            except Exception as exc:  # noqa: BLE001
                print(f"  batch@{start} attempt {attempt + 1}: {exc}")
                await asyncio.sleep(2 * (attempt + 1))
                got = []
        source_ids = [r[0] for r in batch]
        if not got:
            # Never drop a batch the model failed to rewrite: carry the
            # originals through unchanged so nothing is lost.
            print(f"  batch@{start}: {len(batch)} -> kept verbatim (model failed)")
            for r in batch:
                merged.append({"slug": "", "content": r[2], "keep_key": r[1],
                               "importance": r[3], "category": r[6],
                               "task_category": r[5], "sources": [r[0]]})
            continue
        print(f"  batch@{start}: {len(batch)} -> {len(got)}")
        for item in got:
            # Attribute the merged lesson to the highest-importance source it covers.
            best = max(batch, key=lambda r: (r[3] or 0, r[4] or 0))
            merged.append({**item, "importance": best[3], "category": best[6],
                           "task_category": best[5], "sources": source_ids})

    out = Path(f"/tmp/consolidated-{mtype}.json")
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(rows)} -> {len(merged)} entries; proposal: {out}")
    if not apply:
        print("Dry run. Re-run with --apply to write (originals archived first).")
        return 0

    backup = db_path().with_suffix(f".backup-{datetime.now():%Y%m%d-%H%M%S}.db")
    src = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
    dst = sqlite3.connect(backup)
    src.backup(dst)
    dst.close()
    src.close()
    print(f"backup: {backup}")

    archive_dir = Path.home() / ".crabagent" / "memory-archives"
    archive_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, archive = tempfile.mkstemp(prefix=f"user-{user_id}-lesson-consolidation-", suffix=".json",
                                   dir=archive_dir)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "user_id": user_id,
                   "reason": f"consolidated {len(rows)} lessons into {len(merged)}",
                   "memories": [{"id": r[0], "key": r[1], "content": r[2]} for r in rows]},
                  fh, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())
    print(f"archive: {archive}")

    covered = sorted({sid for item in merged for sid in item.get("sources", [])})
    if len(covered) != len(rows):
        missing = {r[0] for r in rows} - set(covered)
        print(f"refusing to apply: {len(missing)} rows not covered by any batch")
        return 3

    db = sqlite3.connect(db_path(), timeout=30)
    db.execute("BEGIN IMMEDIATE")
    ids = covered
    id_list = ",".join(map(str, ids))
    db.execute(f"DELETE FROM memory_embedding WHERE memory_id IN ({id_list})")
    db.execute("DELETE FROM conversation_memory_injections WHERE memory_uid IN "
               f"(SELECT memory_uid FROM agent_memory WHERE id IN ({id_list}))")
    db.execute(f"DELETE FROM agent_memory WHERE id IN ({id_list}) AND user_id = ?", (user_id,))

    now = datetime.now().isoformat(sep=" ")
    inserted = 0
    for item in merged:
        if item.get("keep_key"):
            # Failed batch: reinsert the original untouched.
            db.execute(
                "INSERT INTO agent_memory (memory_uid, content_revision, visibility_epoch, user_id, "
                "memory_type, agent_name, category, key, content, importance, confidence, "
                "source_session, access_count, source, task_category, scope, workspace_path, "
                "recall_policy, evidence, evidence_kind, supersedes_id, created_at, updated_at) "
                "VALUES (lower(hex(randomblob(16))), 1, 1, ?, 'agent_lesson', ?, ?, ?, ?, ?, 1.0, "
                "'', 0, 'llm', ?, 'agent', '', 'query_only', '', '', NULL, ?, ?)",
                (user_id, agent, item.get("category") or "effective_strategy", item["keep_key"],
                 item["content"], item.get("importance", 0.65),
                 item.get("task_category") or "", now, now),
            )
            inserted += 1
            continue
        key = (f"user_pref:{item['slug']}" if mtype == "user_preference"
               else f"lesson:{agent}:{item['slug']}")
        exists = db.execute(
            "SELECT id FROM agent_memory WHERE user_id=? AND key=? AND memory_type=?",
            (user_id, key, mtype),
        ).fetchone()
        if exists:
            db.execute("UPDATE agent_memory SET content=?, updated_at=? WHERE id=?",
                       (item["content"], now, exists[0]))
            continue
        db.execute(
            "INSERT INTO agent_memory (memory_uid, content_revision, visibility_epoch, user_id, "
            "memory_type, agent_name, category, key, content, importance, confidence, "
            "source_session, access_count, source, task_category, scope, workspace_path, "
            "recall_policy, evidence, evidence_kind, supersedes_id, created_at, updated_at) "
            "VALUES (lower(hex(randomblob(16))), 1, 1, ?, ?, ?, ?, ?, ?, ?, 1.0, "
            "'', 0, 'llm', ?, ?, '', 'query_only', '', '', NULL, ?, ?)",
            (user_id, mtype, "" if mtype == "user_preference" else agent,
             item.get("category") or "other", key, item["content"],
             item.get("importance", 0.6), item.get("task_category") or "",
             "global" if mtype == "user_preference" else "agent", now, now),
        )
        inserted += 1
    db.commit()
    print(f"deleted {len(ids)}, inserted {inserted}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-id", type=int, required=True)
    ap.add_argument("--agent", required=True)
    ap.add_argument("--type", default="agent_lesson",
                    choices=["agent_lesson", "user_preference"])
    ap.add_argument("--model", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    return asyncio.run(run(args.user_id, args.agent, args.model, args.apply, args.type))


if __name__ == "__main__":
    raise SystemExit(main())

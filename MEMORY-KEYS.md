# Memory key strategy

Status: implemented 2026-11-24. Supersedes the `user_pref:<category>:<slug>` and
`lesson:<agent>:llm:<md5>` schemes.

## The problem with the old scheme

The key carried two things at once: identity and description.

```
user_pref:disk-cleanup:3f9a1c2b7d4e   # identity depended on category + hash
lesson:coder:llm:6837c54bff2d         # identity was a hash of the content
```

Both break the same way: **the key changes when it should not**.

- `user_pref:...` embedded the category, and the extractor invented ~200
  one-off categories. Re-extracting the same preference under a different tag
  produced a different key, so duplicates never converged.
- `lesson:...` hashed the content. Editing one word of a lesson minted a new
  key, so an existing lesson could never be refined in place.
- A hash suffix is unreadable and unsearchable. Ordering by key told you
  nothing, and a human could not tell whether two rows were the same subject.

## Principles

1. **The key is an identity, not a description.** One subject → one key, always.
2. **Only stable, semantic fields may compose a key.** No hashes, timestamps,
   counters, or model-invented categories.
3. **Mutable metadata stays out of the key.** Category, importance, evidence and
   scope can change freely without minting a new row.
4. **A key is human-readable and hand-editable.** It survives a migration, a
   merge, and a review by the user in the Memory page.

## Format

| memory_type | key format | example |
|---|---|---|
| `user_preference` | `user_pref:<slug>` | `user_pref:verify-build-before-install` |
| `agent_lesson` | `lesson:<agent>:<slug>` | `lesson:coder:restart-backend-after-edit` |
| `team` | unchanged | `convention:release-pipeline-pypi` |

`team` keys already follow this shape (a semantic prefix plus a slug) and are
curated by hand through `memory_save`, so they are left alone.

### Slug rules

- 2–5 lowercase English words, hyphen-separated
- 3–48 characters, `[a-z0-9-]` only
- Names the **subject**, not the episode: `cache-hit-measurement`, not
  `when-the-user-asked-about-cache`
- Rejected outright: `general`, `misc`, `other`, pure digits, single characters

`category` (one of the 12 closed categories) is stored as a column and used for
filtering, display and recall weight. It is **not** part of the key, so getting
the category wrong no longer fragments a subject across rows.

## Uniqueness and conflict resolution

The identity tuple is `(user_id, memory_type, scope, workspace_path,
agent_name, key)`. `agent_memory.key` has no unique index on purpose: the same
slug may legitimately exist once per workspace or once per agent.

Resolution order on write:

1. **Same tuple exists** → update in place. Content is replaced, revision
   increments via the schema trigger, and embeddings are invalidated.
2. **Same slug under a different category** → still the same key, so still an
   update. This is the bug the old scheme caused.
3. **Different slug, near-identical content** → the merge model decides
   `refine` (fold into the existing row, keep its key) or `contradicts`
   (insert a new row with `supersedes_id` pointing at the old one).
4. **Same slug on migration with conflicting content** → keep one row, append
   the other's content as a new paragraph so no fact is lost, and record the
   absorbed key in `evidence` as `merged-from:<key>`.

Never resolve a collision by appending a hash, a counter, or a date.

## Migration of existing rows

One-off, idempotent, run with a backup. Mappings:

| from | to |
|---|---|
| `user_pref:<topic>:<hash>` | `user_pref:<slug>` (slug = topic when usable) |
| `lesson:<agent>:llm:<hash>` | `lesson:<agent>:<slug>` (slug generated) |
| `user_pref:<topic>` (already migrated) | unchanged |

Slug selection for preferences reuses the legacy topic segment when it is a
usable slug (`disk-cleanup`, `cross-env-verification`); generic topics
(`general`, `resource`, `comparison`, `design`, `features`, `accuracy`, …) are
regenerated from the content by the model, because they do not identify a
subject.

Collisions created by the migration are resolved by §"Uniqueness": the row with
higher `importance` (then more `access_count`, then newer) keeps the key and the
other's content is appended to it. Every absorbed row is written to the archive
file first, so the Memory page can restore it.

## What this changes for recall

Recall does not read the key for identity — it uses `memory_uid`. But two things
improve:

- `agent_memory_get_by_agent` ordering by key becomes meaningful.
- The memory quality report's "random key" bucket should report **0** after the
  migration, and any non-zero count becomes a real regression signal.

## Implementation checklist

- `preference_schema.build_key` → `user_pref:<slug>`
- `llm_reflect_lesson` prompt asks for a `Slug:` line; `persist_lesson` prefers
  `lesson:<agent>:<slug>` and falls back to the hash only when no slug is given
- `memory_save` tool description documents the format
- Migration script: dry-run prints the mapping and collisions; `--apply` writes
  the archive first, then renames in one transaction

## Execution log (2026-11-24)

450 rows migrated for user 1; 0 hash keys remain.

| step | script | result |
|---|---|---|
| generate slugs | `scripts/generate_memory_slugs.py` | 240 generated by the model |
| rename + fold | `scripts/migrate_memory_keys.py` | 426 renamed, 24 duplicates folded into 15 rows |
| refine folded content | `scripts/refine_merged_memories.py` | 9 rows compressed (worst 2080 → 338 chars) |
| junk lessons | manual, archived | 11 reasoning-trace fragments deleted |
| rewrite polluted lessons | model, archived | 8 rows stripped of thinking preambles |

Two findings worth keeping:

- **Fold-then-append is not enough.** Appending absorbed paragraphs left
  2080-character rows of the same sentence rephrased. Content that is
  near-identical must be *dropped*, not concatenated — and what remains still
  needs one compression pass.
- **The extractor stored its own reasoning as lessons.** Eleven rows began with
  "Hmm," / "Let me phrase it" / "Category: code?" — the model answered with its
  thinking instead of the requested format. `looks_like_meta_lesson` missed all
  of them, so the guard needs a prefix check, not just a keyword check.

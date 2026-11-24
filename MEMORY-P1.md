# Memory P1: tightening automatic extraction

Status: §1-§4 and §6 implemented (2026-11-24); §5 (lessons) partially; see
"Implementation notes" at the end for the deviations found while building it.

## Why P1

P0 made recall work per turn and bounded the resident pool. The remaining
noise comes from what gets written. Read-only analysis of the live database
(2026-11-24) shows:

| Signal | Value | Meaning |
|---|---|---|
| `user_preference` rows | 255, 253 from LLM | almost everything is auto-extracted |
| keys with random suffix | 251 / 255 | merge never reuses a key |
| `category` values | ~200 distinct, mostly one-off tags | categories do not cluster |
| same-prefix content | "When the use…" x17, "When the ass…" x6 | near-duplicates persist |
| `agent_lesson` rows | 219, 211 from `coder` | lessons accumulate per agent, never reviewed |

Four structural causes, all in `core/agent/reflect.py` and `memory_merge.py`:

1. `merge_preference` returns `False` for `category == "general"`, and the
   extractor is free to invent categories, so most candidates never reach the
   similarity check.
2. The extractor prompt says "return the existing key when refining", but the
   caller ignores a returned key and always mints `user_pref:{cat}:{md5}`.
3. The prompt asks for what the *user* demonstrated, yet a large share of rows
   read "When the assistant…" or "When the user asks for X, do Y". These are
   one-off behaviours or single-turn instructions, not stable preferences.
   Example: a one-time "直接删除" authorisation became an unconditional rule.
4. `existing_preferences` passed to the extractor is the user's entire
   preference table. That is expensive, and it makes "is this related?" hard to
   answer, which pushes the model toward emitting a new entry.

## Goals and non-goals

Goals:

- Fewer, more trustworthy automatic writes; each one traceable to evidence.
- Preferences and lessons stay distinct: preferences describe the user,
  lessons describe what worked for an agent on a task.
- Duplicates converge on the same key instead of accumulating.
- A wrong entry can be traced to the session that produced it.

Non-goals (deliberately out of P1):

- Vector retrieval upgrades (P2).
- Bulk cleanup of the 255 existing rows. P1 ships a *report* of suspected
  low-quality rows; deletion stays a user decision in the Memory page.
- Changing the `memory_save` tool contract; it already lets the agent choose
  scope and policy explicitly.

## Design

### 1. Evidence-gated preferences

A preference is written only when the conversation contains explicit evidence.
The extractor returns an `evidence` quote per candidate; a candidate without a
verbatim quote from a user message is dropped before persistence.

Accepted evidence kinds (returned as `kind`):

| kind | example | stored as |
|---|---|---|
| `correction` | user corrects the assistant's behaviour | preference |
| `repeated_request` | same ask appears in ≥2 user turns of the run | preference |
| `explicit_choice` | user picks between options or rejects one | preference |
| `standing_rule` | "以后都…" / "from now on" / "always" | preference |

Rejected: `assistant_behaviour` (describes what the assistant did),
`single_instruction` (one-off task instruction), `inferred` (no quote).

The prompt is rewritten to ask for **the user's words**, not a summary of the
run. Few-shot examples include one rejected `assistant_behaviour` case drawn
from the real `post-restart-verification` row so the model sees the boundary.

`importance` is no longer model-chosen. It is derived from `kind`:
`standing_rule` 0.8, `correction` 0.7, `explicit_choice` 0.6,
`repeated_request` 0.6. This removes a free parameter the model has no basis
for estimating.

### 2. Stable keys via a closed category set

Replace free-form categories with a fixed list the extractor must choose from:

```
language, response_style, code_style, tooling, workflow, delivery_format,
safety, collaboration, memory, cost, testing, other
```

Key = `user_pref:{category}:{slug}` where `slug` is a 2–4 word kebab-case
subject produced by the model (`user_pref:workflow:verify-build-before-install`).
If the returned key already exists for the user, the row is **updated in place**
(see §3) instead of a new row being created. `other` is allowed but is
reviewed by the quality report (§6).

### 3. Merge that actually runs

`merge_preference` changes:

- Drop the `category == "general"` early return (the set is closed now, so
  the problem disappears).
- Candidate set: same `user_id`, same `category`, plus top-N by string
  similarity across *all* categories (catches miscategorised duplicates).
- Merge decision stays with the model, but the check becomes a structured
  comparison: same subject? contradictory? one refines the other? Only
  "refines" merges; "contradictory" creates a new row with `supersedes`
  pointing at the old one, and the Memory page shows the pair.
- If the model returned an existing key, skip similarity search entirely and
  go straight to the in-place update path with a revision check.

### 4. Passing fewer existing rows to the extractor

Send the extractor only the user's preferences in the same closed category as
each candidate *after* extraction, not before. Concretely:

1. Extract with no `existing_preferences` block (cheaper prompt, less anchor).
2. For each candidate, run §3 against the user's rows in that category.
3. Only if the model must choose between "new" and "refine" does it see
   the ≤10 same-category rows.

This cuts the prompt from ~255 rows to ≤10 per candidate and removes the
"everything is already known, so emit something new" pressure.

### 5. Lessons: extract from the run, scoped to the task

`llm_reflect_lesson` keeps its current shape but gains:

- Input is the **last** user turn and the final assistant text, not the first
  user message (today a long session with several tasks pairs the first task
  with the last answer).
- `task_category` must come from the closed set `code | research | analysis |
  writing | general`; anything else maps to `general`.
- Lessons get `source_session` (already present) and a new `evidence` field
  with the tool calls or file paths that support them. Lessons without
  evidence are dropped.
- Per-agent lesson cap: when an agent has more than 40 lessons, the lowest
  `importance` rows with `access_count == 0` older than 60 days are listed in
  the quality report rather than auto-deleted.

### 6. Quality report (read-only)

A new endpoint `GET /api/memory/quality` returns:

- preferences whose `kind` would be rejected under §1 but exist today
  (heuristic: content starts with "When the assistant" / "the user asks");
- random-suffix keys and their nearest same-category neighbour with similarity;
- `agent_lesson` rows per agent beyond the cap.

The Memory page gets a "待清理" filter that lists these. Deletion stays manual.
This is how the 255 existing rows get triaged without a risky bulk update.

## Data model changes

Add to `agent_memory` (via `ensure_column`, no table rebuild):

- `evidence` TEXT — verbatim user quote or tool-call reference.
- `evidence_kind` VARCHAR(32) — one of the accepted kinds, or blank for
  agent-written (`memory_save`) rows.
- `supersedes_id` INTEGER NULL — set when a new row replaces a contradictory one.

`content_revision` / `visibility_epoch` triggers already cover these columns
because they are not in `content_fields`; `evidence` should be added to
`content_fields` so a corrected quote bumps the revision.

## Evaluation

Offline, on a replay corpus of 20 past sessions (chosen by the user, spanning
coding / research / writing):

| Metric | Today (baseline) | Target |
|---|---|---|
| preferences written per session | ~3 | ≤1 |
| rows with evidence quote | 0% | 100% of new rows |
| rows starting with "When the assistant" | ~25% of sample | 0 |
| duplicate rate (sim ≥0.85 within category) | high (17 same-prefix) | ≤5% |
| extractor prompt tokens per run | ~255 rows injected | ≤10 rows injected |

Online, after two weeks: share of resident `always` rows, recall precision
sampled by hand on 30 turns, and whether users delete auto-written rows
(deletion rate is the clearest "this was wrong" signal).

## Rollout

1. Ship §6 report first (read-only, zero risk) so the user can see the backlog.
2. Ship §1–§4 behind `memory_auto_extract` (already exists) with a new
   `settings.memory_extraction_v2` flag defaulting to **on** for new writes;
   old rows are untouched.
3. Ship §5 for lessons under the same flag.
4. After evaluation, decide whether to bulk-triage the 255 legacy rows using
   the report, category by category, with the user confirming each batch.

## Risks

- Stricter gates may write *too little*. Mitigation: `memory_save` remains
  available to the agent for explicit "记住这个" requests, and the
  `repeated_request` kind still catches habits that show up across turns.
- Closed categories may mis-bucket. `other` is the escape hatch and is
  surfaced by the report.
- The merge model call still costs one LLM round-trip per candidate. Cap at
  three candidates per run and skip the call when the model reused a key.


## Implementation notes

Built in `src/crabagent/core/agent/preference_schema.py` (closed vocabulary +
evidence gate), `reflect.py` (prompt, parsing, persistence),
`memory_merge.py` (stable-key merge) and `middlewares/reflect_middleware.py`
(last-user-turn task, verbatim user turns). Switch:
`settings.memory_extraction_v2` (default on). Tests:
`tests/test_preference_extraction_p1.py`.

Deviations from the design above, each found by testing:

- **Thresholds are byte-based, not character-based.** `MIN_CONTENT_CHARS = 8`
  rejected "用中文回复。" (6 chars, complete) while accepting 8 latin
  characters of noise. CJK carries ~3 bytes per character, so all length
  floors now compare encoded bytes.
- **`if not llm_params` was too strict.** The contract of
  `_resolve_llm_params` is *None means failure*, so a legitimately empty dict
  silently disabled extraction. Now checked with `is None`.
- **Merge similarity floor lowered to 0.72** (was 0.85) and the candidate set
  widened from one category to the whole preference table. The old
  same-category filter could not see real duplicates once categories stopped
  being stable.
- **Exact key match short-circuits similarity.** When a candidate carries a
  key that already exists, the model is still consulted to decide
  refine-vs-contradict, but the candidate pair is chosen without a search.
- **§5 lessons deferred.** `llm_reflect_lesson` still mints a hash key
  (`lesson:<agent>:llm:<md5>`); dedup by similarity already worked there, so
  the change is additive and lower risk. Worth doing next.

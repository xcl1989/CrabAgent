# Memory P0: per-turn recall in Web chat

## Entry points and precedence

Every real Web chat turn, including a queued follow-up, has a persisted user
message anchor. Scheduled/automatic prompts do not create new recall batches.
The base system prompt and AGENTS.md remain authoritative and memory-free
apart from the project rules. The existing `memory_auto_recall` switch controls
both first-time recall and historical replay. CLI and delegated agents are unchanged.

Every Web chat model receives still-valid snapshots at their original user
message positions. There is no model allowlist and no need to switch Agents.
Historical text is replayed verbatim from the snapshot, never reconstructed by
rerunning recall or by reading the current memory body.

## Candidate selection

Candidates are filtered by user, workspace, Agent and recall policy before
ranking. Only `convention` and `decision` team entries default to `always`;
topic knowledge (architecture, api, feature, project) and all lessons are
`query_only` and only appear when relevant. Resident entries share a fixed
byte cap and at most half of the slots, so relevance-ranked entries always
keep room. Query-only notes need an exact key hit or at least two non-generic
lexical overlaps (ASCII identifiers, CJK bigrams minus a stoplist); generic
bigrams such as 前端/显示/消息 alone never match. Workspace-specific rules
precede global ones; relevance precedes importance. Blank-policy legacy
knowledge is not promoted unconditionally; unknown policies are excluded. Select at most
four records (also respecting `memory_max_inject`), stay within a UTF-8 byte
budget (2400 per record, 6000 per new turn, 20000 across replayed history), and mark truncated excerpts. The
per-record budget is byte-based, so long Chinese rules truncate sooner than
English ones. No vector service or schema change is
required. The scan is read-only; a recall miss writes no new snapshot. Tool
iterations only revalidate the selected records; they never repeat the scan.
Already-present memories are not injected twice. When the cumulative budget
is full, skip new additions rather than evicting existing valid snapshots.
Lexically distant paraphrases are an explicit limitation in P0.

## Admission and visibility

Before each provider request, recheck ownership, scope, revision, branch and
visibility under the existing SQLite writer transaction. Removing a memory in
the Memory page prevents subsequent replay. Edits invalidate the old snapshot;
a matching later turn can still recall the new version. Retries only narrow
the previous admission set; SDK retries are disabled for this guarded path.
Memory is untrusted reference data and does not change the stored user message.

## Chat feedback and cache verification

Show one collapsed card per anchor. The live event follows adapter handoff;
the history API derives cards from visible, admitted snapshots rather than
storing a second copy. Admission records dispatch eligibility, not proof that
the provider received or acted on the inputs. Revoked snapshots no longer
appear after refresh. Cards are never inserted into model history or search.

Regression tests compare prior request messages with the exact prefix of the
next request and cover revisions, deletion and branch boundaries. Actual cache
hits depend on the provider, cache thresholds and TTL; switching models,
compression and revocation can break the prefix. After rollout, compare the
existing cached-token and prompt-token usage fields in real repeated requests.

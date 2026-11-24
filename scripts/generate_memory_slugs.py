"""Generate semantic slugs for legacy memories (companion to migrate_memory_keys.py).

Reads the rows that need a slug, asks the configured model for a short
kebab-case subject name per row, and writes a mapping JSON:

    {"<memory_id>": "<slug>", ...}

The migration script consumes it via ``--slugs``.

Usage::

    python3 scripts/generate_memory_slugs.py --user-id 1 --out /tmp/slugs.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import litellm  # noqa: E402
from migrate_memory_keys import db_path, plan  # noqa: E402

BATCH = 8
# Overridable so a provider whose catalogue does not contain settings.default_model
# (e.g. a zhipu account with gpt-4o configured) can still run this.
MODEL_OVERRIDE = ""
SYSTEM = (
    "You name memory records. For each item return ONE slug: 2-4 lowercase English "
    "words joined by hyphens that name the SUBJECT (not the episode). "
    "Examples: restart-backend-after-edit, verify-build-before-install, "
    "cache-hit-measurement. Never use hash-like strings, digits, dates, or generic "
    "words such as general/other/misc/preference. If two items share a subject, "
    "give them the SAME slug.\n\n"
    "Reply with one line per item, exactly: <id>|<slug>\nNo prose, no bullets."
)


def _parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "|" not in line:
            continue
        ident, slug = line.split("|", 1)
        ident = re.sub(r"[^0-9]", "", ident)
        slug = re.sub(r"[^a-z0-9-]+", "-", slug.strip().lower()).strip("-")
        if ident and slug and len(slug) >= 3:
            out[ident] = slug
    return out


async def run(user_id: int, out_path: Path) -> int:
    from crabagent.core.agent.reflect import _resolve_llm_params
    from crabagent.core.config import settings
    from crabagent.core.provider_store import get_default_provider, resolve_model_for_provider

    conn = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
    _, needs = plan(conn, user_id)
    conn.close()
    if not needs:
        print("nothing to do")
        return 0

    params = await _resolve_llm_params(None)
    if params is None:
        print("no provider configured")
        return 2
    provider = await get_default_provider()
    model = MODEL_OVERRIDE or (
        resolve_model_for_provider(provider, settings.default_model) if provider else settings.default_model
    )
    print(f"model: {model}")

    mapping: dict[str, str] = {}
    if out_path.exists():
        mapping = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"resuming with {len(mapping)} existing entries")

    todo = [n for n in needs if str(n["id"]) not in mapping]
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        listing = "\n".join(f"{n['id']}|{n['memory_type']}|{(n['content'] or '')[:220]}" for n in batch)
        for attempt in range(3):
            try:
                response = await litellm.acompletion(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": listing},
                    ],
                    # Reasoning models spend the budget on reasoning_content first;
                    # a small cap leaves content empty with finish_reason=length.
                    max_tokens=4000,
                    temperature=0.1,
                    **params,
                )
                text = response.choices[0].message.content or ""
                got = _parse(text)
                for n in batch:
                    slug = got.get(str(n["id"]))
                    if slug:
                        mapping[str(n["id"])] = slug
                break
            except Exception as exc:  # noqa: BLE001
                print(f"  batch {start} attempt {attempt + 1} failed: {exc}")
                await asyncio.sleep(2 * (attempt + 1))
        out_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
        done = min(start + BATCH, len(todo))
        print(f"  {done}/{len(todo)} (mapped {len(mapping)})")

    missing = [n for n in needs if str(n["id"]) not in mapping]
    print(f"total mapped {len(mapping)} / {len(needs)}")
    if missing:
        print(f"still missing {len(missing)}:")
        for n in missing[:10]:
            print(f"  [{n['id']}] {(n['content'] or '')[:80]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-id", type=int, required=True)
    ap.add_argument("--out", type=Path, default=Path("/tmp/memory-slugs.json"))
    ap.add_argument("--model", default="", help="override the wire model name")
    args = ap.parse_args()
    global MODEL_OVERRIDE
    MODEL_OVERRIDE = args.model
    return asyncio.run(run(args.user_id, args.out))


if __name__ == "__main__":
    raise SystemExit(main())

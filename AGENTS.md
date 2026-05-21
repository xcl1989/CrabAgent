# Project Rules

## Database Schema Changes
- NEVER delete `crabagent.db` when adding new columns/tables
- SQLAlchemy `create_all()` only creates new tables, it does NOT alter existing ones
- When adding a column to an existing table, add ALTER TABLE logic in `init_db()` in `src/crabagent/core/database.py`
- Example pattern:
  ```python
  async with conn.execute(text("PRAGMA table_info(conversations)")) as result:
      columns = [row[1] for row in await result.fetchall()]
  if "tokens" not in columns:
      await conn.execute(text("ALTER TABLE conversations ADD COLUMN tokens INTEGER DEFAULT 0"))
  ```

## General
- Provider configs are user data stored in `crabagent.db` — never delete the DB without explicit user approval
- When in doubt, ask the user before any destructive operation

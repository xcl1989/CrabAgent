# Project Rules

## Version
- Current: **0.3.1** (browser screenshot inline display)
- Version in: `pyproject.toml`, `src/crabagent/serve/app.py`, CLI banner in `src/crabagent/cli/__main__.py`

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

## Browser Automation (v0.3.0)
- Playwright is an **optional dependency**: `pip install 'crabagent[browser]'`
- Tools only register if playwright is importable — `PLAYWRIGHT_AVAILABLE` flag in `browser.py`
- `BrowserManager` stored in `context.metadata["_browser_manager"]`, lazily initialized on first call
- 7 tools: `browser_navigate`, `browser_click`, `browser_type`, `browser_screenshot`, `browser_extract`, `browser_scroll`, `browser_close`
- Screenshots saved to `/tmp/crabagent_screenshots/`
- Headless by default; set `CRAB_BROWSER_HEADLESS=false` for headed mode
- Cleanup: `browser_mgr.close()` called in `finally` blocks of both CLI and serve prompt handlers
- Import in CLI: `try: import crabagent.core.agent.tools.browser` (wrapped in try/except)
- Import in serve: same pattern in `prompt.py` top-level

## General
- Provider configs are user data stored in `crabagent.db` — never delete the DB without explicit user approval
- When in doubt, ask the user before any destructive operation

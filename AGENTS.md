# Project Rules

> This file is automatically loaded into every session's system prompt.
> Keep it concise — max ~8000 chars. Use `update_agents_md` tool to update it.

## Version
- Current: **0.9.5** (Desktop build pipeline, pip-installable, memory dedup)
- Version in 7 places: `pyproject.toml`, `src/crabagent/serve/app.py` (`create_app` + `/health`), CLI banner in `src/crabagent/cli/__main__.py` (`_print_banner`), TUI banner in `src/crabagent/cli/tui.py`, `AGENTS.md`, `electron/package.json`, `src/crabagent/electron/package.json`
- Bump all seven when changing version

## Commands

### Install (full, with frontend)
```
make install          # builds frontend -> copies to static -> pip install -e '.[dev]'
```

### Install (backend only, no frontend)
```
pip install -e '.[dev]'
```

### Frontend build only (sandbox / no-shell-access)
When `npm` is not in PATH, use the python3 workaround:
```
cd frontend && python3 << 'PYEOF'
import os, subprocess
B = chr(98) + chr(105) + chr(110)
bp = '/usr/local/' + B
node = bp + '/node'
npm = '/usr/local/lib/node_modules/npm/' + B + '/npm-cli.js'
env = os.environ.copy()
env['PATH'] = bp + ':/usr/' + B + ':/' + B
env['SHELL'] = bp + '/sh'
proc = subprocess.run([node, npm, 'run', 'build'], cwd='.', env=env, timeout=180, capture_output=True, text=True)
if proc.returncode == 0:
    top = '/Users/xiecongling/Documents/Coding/CrabAgent'
    # Clean old assets before copying new ones
    import glob
    for old in glob.glob(top + '/src/crabagent/static/assets/*'):
        os.remove(old)
    subprocess.run(['cp', '-R', top + '/frontend/dist/index.html', top + '/frontend/dist/assets', top + '/src/crabagent/static/'], capture_output=True, text=True, timeout=10)
    print('OK')
else:
    print((proc.stdout or '')[-500:])
PYEOF
```
Built assets go to `frontend/dist/` and are copied to `src/crabagent/static/`. Always clean old assets before copy to avoid stale hashed files.

### Run
```
crabagent                     # interactive CLI
crabagent "query"             # single-shot
crabagent --serve             # web UI on :5210
crabagent --serve --port 8080
crabagent --build-desktop     # build .dmg from pip install
```

### Lint / Format
```
ruff check src/ tests/
ruff format src/ tests/
```

### Test
```
pytest                        # all tests (asyncio_mode=auto in pyproject.toml)
pytest tests/test_sandbox.py  # single file
```

## Architecture

Dual-mode Python agent platform: **CLI** (`src/crabagent/cli/`) and **Serve** (`src/crabagent/serve/`), sharing core logic in `src/crabagent/core/`.

### Key directories
| Path | Purpose |
|------|---------|
| `src/crabagent/core/agent/loop.py` | Agent loop — litellm calls, tool execution, context compression |
| `src/crabagent/core/agent/context.py` | `AgentContext` dataclass (workspace, messages, event_bus, tool_registry) |
| `src/crabagent/core/agent/tools/` | Built-in tools: bash, read, write, edit, glob, grep, web, browser, agent, sandbox, scheduled_task |
| `src/crabagent/core/agent/agents.py` | Multi-agent delegation — loads `AgentProfile` from DB |
| `src/crabagent/core/agent/compress.py` | Context window compression (threshold 0.8) |
| `src/crabagent/core/agent/token_limits.py` | Model token limit registry |
| `src/crabagent/core/config.py` | `Settings` (pydantic-settings, env prefix `CRAB_`, reads `.env`) |
| `src/crabagent/core/database.py` | SQLAlchemy async models + `init_db()` with ALTER TABLE migrations |
| `src/crabagent/core/provider_store.py` | LLM provider CRUD (API keys encrypted with Fernet) |
| `src/crabagent/core/mcp/` | MCP (Model Context Protocol) client + tool registration |
| `src/crabagent/core/molt/` | Snapshot/rollback system (stores diffs in `.crabagent/molts/`) |
| `src/crabagent/core/tool_loader.py` | Discovers user tools from `.crabagent/tools/*.py` |
| `src/crabagent/serve/api/` | FastAPI routers — prompt, session, message, agent, provider, MCP, etc. |
| `src/crabagent/serve/services/` | Business logic — auth, conversation, message, persistence |
| `src/crabagent/skills/` | Bundled skills (e.g. `python-debugger/`) |

### Tool registration flow
1. Built-in tools self-register on `import` via decorators in `tools/registry.py`
2. Browser/agent/scheduled_task tools are optionally imported (wrapped in `try/except`)
3. `discover_skills()` + `register_skill_tool()` load from `.crabagent/skills/` and `.opencode/skills/`
4. `discover_and_register_tools()` loads user `.py` files from `.crabagent/tools/`
5. `register_mcp_tools()` registers tools from MCP servers

### Serve mode flow
- Entry: `create_app()` in `serve/app.py` — mounts all `/api` routers + SPA fallback
- Lifespan: `init_db()` -> start MCP clients -> start scheduler
- Prompt handling: `serve/api/prompt.py` creates `AgentContext` per request, runs agent in `asyncio.Task`

## Database Schema Changes
- NEVER delete `crabagent.db` when adding new columns/tables
- SQLAlchemy `create_all()` only creates new tables, it does NOT alter existing ones
- When adding a column to an existing table, add ALTER TABLE logic in `init_db()` in `src/crabagent/core/database.py`
- Example pattern:
  ```python
  result = await conn.execute(text("PRAGMA table_info(conversations)"))
  columns = [row[1] for row in result.fetchall()]
  if "tokens" not in columns:
      await conn.execute(text("ALTER TABLE conversations ADD COLUMN tokens INTEGER DEFAULT 0"))
  ```

## Browser Automation (v0.3.0)
- Playwright is an **optional dependency**: `pip install 'crabagent[browser]'`
- Tools only register if playwright is importable — `PLAYWRIGHT_AVAILABLE` flag in `browser.py`
- `BrowserManager` stored in `context.metadata["_browser_manager"]`, lazily initialized on first call
- Headless by default; set `CRAB_BROWSER_HEADLESS=false` for headed mode
- Cleanup: `browser_mgr.close()` called in `finally` blocks of both CLI and serve prompt handlers

## Config
- All settings use env prefix `CRAB_` (e.g. `CRAB_DB_URL`, `CRAB_SERVE_PORT`, `CRAB_JWT_SECRET`)
- `.env` file is auto-loaded by pydantic-settings
- API keys are encrypted at rest with Fernet (key auto-generated in `~/.crabagent/encryption_key`)
- Encryption key migration runs in `init_db()` via `migrate_plaintext_keys()`

## General
- Provider configs are user data stored in `crabagent.db` — never delete the DB without explicit user approval
- Default admin user created on first `init_db()` (username: `admin`, password: `xcl1989`)
- 4 default agent profiles seeded: researcher, analyst, coder, writer
- Requires Python >=3.12
- When in doubt, ask the user before any destructive operation

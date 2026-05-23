# 🦀 CrabAgent

> **AI Team Command Center** — Build a team of specialized AI agents, delegate tasks in parallel, and watch them work in real-time. All from a local web dashboard.

CrabAgent is a local-first AI agent platform. Run it from any project directory via CLI or browser. Your data stays local, your API keys are encrypted, and you pick any LLM provider.

---

## What Makes It Different

| Feature | Description |
|---------|-------------|
| **🤖 AI Team** | Create custom agent profiles; delegate tasks to multiple agents in parallel; each agent can use its own model |
| **📋 Task Board** | Real-time right-side panel showing each agent's status (running/done/error), progress, and tool calls |
| **@mention Delegation** | Type `@researcher search for X` and CrabAgent auto-delegates, or click agents from the toolbar |
| **🔀 Parallel Execution** | Multiple agents run simultaneously — researcher searches while coder debugs while analyst compares |
| **📊 Result Compare** | Side-by-side view of all agent outputs, with one-click Markdown export |
| **⏱ Scheduled Tasks** | Agents run autonomously on a cron schedule with push notifications |
| **🌐 Browser Automation** | Playwright-powered headless browser — navigate, click, screenshot, extract |
| **🖼️ Multimodal** | Paste, upload, or drag images directly into chat; auto-detects vision-capable models |
| **🔌 MCP Client** | Connect external MCP servers (stdio + HTTP); tools auto-discover and prefix |
| **🦀 Snapshots** | Auto-snapshot files before changes; rollback anytime without Git |
| **🔒 Privacy** | All data stays local; API keys encrypted at rest; no telemetry |

---

## Quick Start

```bash
pip install 'crabagent[serve]'

crabagent init

# TUI — interactive REPL with slash commands
crabagent

# Web UI
crabagent --serve          # → http://localhost:5210
                           # Default login: admin / xcl1989

# Single-query CLI
crabagent "organize this directory"
crabagent -p deepseek -m deepseek-chat "write a Python script"
```

---

## AI Team — Your Local Command Center

**1. Build your team** — Sidebar → 🤖 Team → + New Agent. Define each agent's role, goal, backstory, and model override.

**2. Delegate tasks** — Three ways to delegate:
- Type `@researcher find competitor pricing` in the chat — auto-detected and sent
- Click the 🤖 button next to the input → select agents → enter task → send
- Click an agent from the toolbar above the input to insert a `@mention`

**3. Watch in real-time** — The right-side Task Board shows every agent's progress:
- 🟣 **Running** — purple pulsing card with live step count and timer
- 🟢 **Done** — green card with elapsed time, tokens, and iteration count
- 🔴 **Error** — red card with error summary

**4. Review results** — Click any card to open the agent's full output, or click 📋 in the top toolbar for a split-pane comparison view of all results. Export to Markdown with one click.

**5. Go parallel** — Use `delegate_parallel` to run multiple agents simultaneously, or the web delegation modal to assign different tasks to different agents.

Built-in agents:

| Agent | Role | Best For |
|-------|------|----------|
| 🔍 Researcher | Web research | Search, browse, data collection |
| 📊 Analyst | Data analysis | Comparison, pattern detection, reports |
| 💻 Coder | Code expert | Write, review, debug, refactor |
| 📝 Writer | Content writer | Write, edit, translate, format |

---

## Scheduled Tasks

Tasks run autonomously on a cron schedule. Define them via conversation or the ⏱ Tasks panel in the sidebar.

```
> Remind me to drink water every day at 11:00
> Check this product page every 30 minutes, notify me if price drops below 500
```

When a task completes, a notification appears in the bell icon. Click to jump to the execution's conversation — full message history, screenshots, and tool outputs are preserved.

---

## Browser Automation

Controlled via Playwright. Install with `pip install 'crabagent[browser]'` then `playwright install chromium`.

Available tools: `browser_navigate`, `browser_click`, `browser_type`, `browser_screenshot`, `browser_extract`, `browser_scroll`.

```
> Open https://news.ycombinator.com and show me the top 5 stories
> Search for "Python async" on Google and extract the results
```

The browser starts lazily (first call only), shares one instance per conversation, and auto-closes on session end. Screenshots appear inline in the chat.

---

## Image / Multimodal Support

Paste (`Ctrl+V`), upload, or drag images into the chat. CrabAgent auto-detects whether the current model supports vision — vision models get native multimodal content, non-vision models get a file-path placeholder.

- Max 5 images per message, 5MB each
- Supported: PNG, JPEG, GIF, WebP
- CLI: `/image /path/to/image.png What's in this image?`

---

## MCP Client

Connect external MCP servers via stdio or HTTP. Tools auto-discover with the prefix `mcp__{server}__{tool}` and are visually distinguished in the chat.

Manage servers from the MCP panel in the sidebar — add, connect, disconnect, view tool counts and connection status.

---

## Web Search & Custom Plugins

**Web Search**: Built-in `web_search` (DuckDuckGo, zero-config) and `web_scrape`. Optionally configure SearXNG for better results.

**Custom Plugins**: Drop a `.py` file in `.crabagent/tools/`:

```python
name = "hello"
description = "Say hello to someone"
parameters = {
    "type": "object",
    "properties": {"name": {"type": "string", "description": "Name"}},
    "required": ["name"],
}
requires_permission = False

def run(name: str) -> str:
    return f"Hello, {name}!"
```

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `/exit`, `/quit` | Exit |
| `/help` | Show help |
| `/clear` | Clear conversation context |
| `/model [name]` | Switch model |
| `/models` | List available models |
| `/sessions` | List recent sessions |
| `/session [id]` | Load a session |
| `/new` | Start new conversation |
| `/molt [cmd]` | Snapshot list/show/rollback |
| `/todo [cmd]` | Manage task list |
| `/skills` | List available skills |
| `/image <path> [msg]` | Send an image |

---

## Configuration

Set via environment variables or `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `CRAB_DB_URL` | `sqlite+aiosqlite:///./crabagent.db` | Database URL |
| `CRAB_JWT_SECRET` | Auto-generated | JWT signing key |
| `CRAB_SERVE_HOST` | `0.0.0.0` | Serve host |
| `CRAB_SERVE_PORT` | `5210` | Serve port |
| `CRAB_MAX_ITERATIONS` | `50` | Max agent iterations |
| `CRAB_MAX_TOKENS` | `4096` | Max response tokens |
| `CRAB_BROWSER_HEADLESS` | `true` | Browser headless mode |

---

## Installation

```bash
pip install 'crabagent[serve]'          # Web UI + API
pip install 'crabagent[browser]'        # Browser automation
pip install 'crabagent[dev]'            # Testing + linting
```

Docker:
```bash
docker compose up -d
```

---

## Project Structure

```
CrabAgent/
├── .crabagent/
│   ├── skills/        # Domain skills (SKILL.md)
│   ├── tools/         # Custom plugin tools
│   └── molts/         # File snapshots
├── src/crabagent/
│   ├── cli/           # CLI entrypoint
│   ├── core/agent/    # Agent loop, tools, context, compression
│   ├── core/mcp/      # MCP client manager
│   └── serve/         # FastAPI + API + scheduler
├── frontend/          # React SPA
├── crabagent.db       # SQLite database
└── Makefile
```

---

## Development

```bash
make install            # Build frontend + install (editable)
ruff check src/ tests/  # Lint
ruff format src/ tests/ # Format
pytest                   # Run tests
```

---

## License

GNU Affero General Public License v3 (AGPLv3) for non-commercial use.
Commercial use requires a separate license. Contact the author.

See [LICENSE](LICENSE).

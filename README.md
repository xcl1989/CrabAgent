# 🦀 CrabAgent

> **AI Team Command Center** — Build a team of specialized AI agents that learn and improve over time. Delegate, parallelize, and watch them work in real-time from terminal or browser.

CrabAgent is a local-first AI agent platform. Run it from any project directory via CLI or browser. Your data stays local, your API keys are encrypted, and you pick any LLM provider.

---

## Why CrabAgent

Unlike other agent platforms where agents are "temporary workers who forget everything," CrabAgent's agents **learn and evolve**:

| Capability | What it means |
|-----------|---------------|
| **🧠 Self-Evolving Agents** | Agents auto-extract lessons from every task — rule engine catches patterns, LLM reflection analyzes strategies. The more you use them, the smarter they get. |
| **🤖 AI Team** | Custom agent profiles with per-agent tool whitelists and model overrides. Delegate, parallelize, or run multi-step pipelines. |
| **📊 Agent Growth Tracking** | View each agent's stats: task count, success rate, lessons learned, common task categories. `ctrl+space agent_stats` |
| **⏱ Scheduled + Real-time** | Agents run on cron schedules or react to @mentions. Real-time streaming of every agent's output. |
| **🦀 Snapshots** | Auto-snapshot files before changes. Roll back anytime without Git. |
| **🔒 Local-first** | All data stays on your machine. API keys encrypted at rest. No telemetry. |

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

## Self-Evolving Agents

This is CrabAgent's core differentiator. Agents don't just execute tasks — they **learn from every execution**.

### How it works

```
Sub-agent completes task
    │
    ├─ Rule Engine (instant)
    │   ├─ High iterations → "Consider breaking tasks into smaller steps"
    │   ├─ Low iterations → "Efficient execution pattern recorded"
    │   └─ Source: rule
    │
    └─ LLM Reflection (best-effort, ~1s)
        ├─ Analyzes strategy: what worked, what didn't
        ├─ Classifies task category: code / research / analysis / writing
        └─ Source: llm
```

### Knowledge persistence

- **Team Knowledge**: Tech stack, architecture decisions, user preferences — auto-injected into every session
- **Agent Lessons**: Per-agent behavioral patterns — loaded before similar tasks
- **Task Records**: Every execution logged (success, elapsed time, tokens, iterations)

### Tracking growth

```bash
# TUI
/agent_stats coder
# → 总任务: 23  成功率: 91%  平均耗时: 14s
# → lessons: 18 (规则: 7, LLM: 11)
# → 常用类别: code(14), analysis(4)

/memory list          # Browse all knowledge
/memory search api    # Keyword search
```

---

## AI Team

### Built-in agents

| Agent | Role | Best For |
|-------|------|----------|
| 🔍 Researcher | Web research | Search, browse, data collection |
| 📊 Analyst | Data analysis | Comparison, pattern detection, reports |
| 💻 Coder | Code expert | Write, review, debug, refactor |
| 📝 Writer | Content writer | Write, edit, translate, format |

### Delegation

- `@researcher find competitor pricing` — @mention auto-delegates
- Click an agent from the toolbar to insert a mention
- `/delegate` command for interactive agent selection
- `delegate_parallel` runs multiple agents simultaneously
- `run_pipeline` chains agents with dependencies

### Real-time monitoring

- 🟣 **Running** — live step count and timer
- 🟢 **Done** — elapsed time, tokens, iterations
- 🔴 **Error** — error summary
- Web: right-side Task Board with split-pane result comparison

---

## More Features

### 🖼️ Multimodal
Paste, upload, or drag images. Auto-detects vision models.

### 🌐 Browser Automation
`pip install 'crabagent[browser]'` + `playwright install chromium`

```
> Open https://news.ycombinator.com and show top 5 stories
> Search "Python async" on Google
```

### 🔌 MCP Client
Connect external MCP servers (stdio + HTTP). Tools auto-discover.

### 📋 Scheduled Tasks
```
> Remind me every day at 11:00 to drink water
> Check product page every 30 minutes, notify if price drops
```

### 🦀 Snapshots
Auto-snapshot before file changes. Roll back with `/molt rollback <id>`.

### 🔧 Custom Plugins
Drop a `.py` file in `.crabagent/tools/`:

```python
name = "hello"
description = "Say hello"
parameters = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
requires_permission = False

def run(name: str) -> str:
    return f"Hello, {name}!"
```

---

## CLI / TUI Commands

| Command | Description |
|---------|-------------|
| `/exit`, `/quit` | Exit |
| `/help` | Show help |
| `/clear` | Clear context |
| `/model [name]` | Switch model |
| `/models` | List models |
| `/provider [cmd]` | Manage providers |
| `/sessions` / `/session [id]` | List / load sessions |
| `/new` | New conversation |
| `/agents [cmd]` | Agent team management |
| `/agent_stats <name>` | Agent growth stats |
| `/delegate [@agent] [task]` | Delegate task |
| `/memory [list\|search\|clear]` | Team memory |
| `/skills` / `/skill <name>` | List / show skills |
| `/molt [cmd]` | Snapshots |
| `/todo [cmd]` | Task list |
| `/export` | Export to Markdown |
| `/image <path> [msg]` | Send image |

---

## Configuration

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

```bash
# Development
make install            # Build frontend + install (editable)
ruff check src/ tests/  # Lint
ruff format src/ tests/ # Format
pytest                   # Run tests
```

---

## Project Structure

```
CrabAgent/
├── src/crabagent/
│   ├── cli/           # CLI entrypoint + TUI
│   ├── core/agent/    # Agent loop, tools, compression, agents
│   ├── core/mcp/      # MCP client manager
│   └── serve/         # FastAPI + API + scheduler
├── frontend/          # React SPA
└── crabagent.db       # SQLite database
```

---

## License

GNU Affero General Public License v3 (AGPLv3) for non-commercial use.
Commercial use requires a separate license. Contact the author.

See [LICENSE](LICENSE).

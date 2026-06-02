# 🦀 CrabAgent

> **AI Team Command Center** — Build a team of specialized AI agents that learn and improve over time. Delegate, parallelize, and watch them work in real-time from terminal or browser.

CrabAgent is a local-first AI agent platform. Run it from any project directory via CLI or browser. Your data stays local, your API keys are encrypted, and you pick any LLM provider.

[![PyPI version](https://badge.fury.io/py/crabagent.svg)](https://badge.fury.io/py/crabagent)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: AGPLv3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

**[English](README.md)** | **[中文](README.zh-CN.md)**

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

# TUI (legacy single-panel)
crabagent --old

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
    │   └─ High iterations (>80% max) → "Decompose complex tasks, use fewer tools per step"
    │
    └─ LLM Reflection (~1-3s)
        ├─ Extracts concrete, actionable insights:
        │   "When searching Chinese news, use English keywords on DuckDuckGo for better results"
        │   "For error-prone sites, prefer web_scrape with direct URLs over web_search"
        ├─ Auto-filters generic/noise responses ("completed in X steps")
        ├─ Also learns from failures: captures what went wrong and how to avoid it
        └─ Source: llm
```

### Knowledge persistence

- **Team Knowledge**: Tech stack, architecture decisions, user preferences — auto-injected into every session
- **Agent Lessons**: Per-agent concrete insights grouped by category (Pitfalls / What Worked) — loaded before similar tasks
- **Task Records**: Every execution logged (success, elapsed time, tokens, iterations)

### Tracking growth

```bash
# TUI
/agent_stats coder
# → 总任务: 23  成功率: 91%  平均耗时: 14s
# → lessons: 18 (规则: 3, LLM: 15)

# Web UI
# → Agent Team → Learning Stats: click agent name to see stats + all lessons

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

### Session Agent Switching

Switch your current agent identity mid-session without losing conversation history:

```bash
# TUI
/agent                  # Popup menu: select from 5 agents
/agent researcher       # Direct switch
/agent default          # Back to all tools

# Web API
POST /api/sessions/{id}/agent  {"agent": "researcher"}
```

- Each agent has different tool sets (researcher gets web tools, coder gets bash+edit, etc.)
- System prompt stays unchanged — **LLM KV cache preserved** across switches
- All messages are tagged with agent info for history tracking
- Model auto-switches if the agent profile specifies one
- Status bar shows current agent: `[deepseek/chat → researcher] Msgs:5 Tok:1234`

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

**Or let agents create tools themselves** — Your agent can write and register custom tools during a session. Tell it what you need and it will generate, validate, and save the tool:

```
> Create a tool that parses CSV files and extracts a column
> Create a tool to fetch weather for a city
```

Tools are saved to `.crabagent/tools/`, auto-registered, and persist across sessions. The agent remembers its created tools via team memory.

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
| `/agent [name]` | Switch current agent |
| `/agent_stats <name>` | Agent growth stats |
| `/delegate [@agent] [task]` | Delegate task |
| `/memory [list\|search\|clear]` | Team memory |
| `/skills` / `/skill <name>` | List / show skills |
| `/molt [cmd]` | Snapshots |
| `/todo [cmd]` | Task list |
| `/export` | Export to Markdown |
| `/image <path> [msg]` | Send image |
| `/runs [agent]` | View agent run history |
| `/abort` | Abort current agent (Ctrl+C) |

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
| `CRAB_WEB_PROXY` | (empty) | HTTP proxy for web_search & web_scrape |

**v0.8.0 Highlights**

- 🎨 **Complete Web UI Redesign** — Brand-new CrabAgent ocean-teal design system with full light/dark theme support (auto-detects system preference). Every component rebuilt on a token-based design foundation — no more hardcoded hex values.
- 🌗 **Light + Dark Theme** — Toggle between warm-cream light and warm-dark themes via the navbar. Persisted in `localStorage` with `prefers-color-scheme` fallback. Every component theme-aware, including charts.
- 🧩 **Reusable UI Library** — New `components/ui/` library: Button, Input, Modal, ConfirmDialog, Toast (sonner), Tooltip (Radix), EmptyState, LoadingState, Skeleton, CodeBlock with copy + syntax highlighting. All components use design tokens.
- 📊 **Theme-Aware Charts** — AgentGrowthChart now uses `useThemeColors()` hook for recharts SVG strokes. Colors automatically follow the active theme.
- 📱 **Mobile Responsive** — SessionList becomes a slide-in drawer on `<md` viewports. Hamburger menu button in the ChatPage toolbar (mobile only). Esc-to-close and tap-overlay-to-close.
- 🗂 **AgentsPage: Modal → Inline Page** — Agent Team panel is now a dedicated inline page at `/agents` (was a modal overlay). Better information density. ChatPage still uses modal mode for quick access.
- 📦 **Bundle Optimization** — Vite `manualChunks` splits vendor code into 4 chunks (react / charts / markdown / ui). Largest single chunk: 380 kB (was 1.22 MB monolith).
- 🎯 **Dashboard Refactor** — DashboardPage replaces 44 inline styles and `AGENT_THEME` hardcoded hex gradients with theme-aware `agentColor()` helper + `--agent-*` CSS vars. Lucide icons replace ASCII glyphs. Empty state for "no pipelines".
- 🔌 **Small Component Cleanup** — TodoWidget, McpStatusBar, FileBrowser, TaskBoard all refactored to use design tokens and Lucide icons.

**v0.7.4 Highlights**

- 🔄 **Session Agent Switching** — Switch agent identity mid-session with `/agent` (TUI) or `POST /api/sessions/{id}/agent` (API). Each agent has different tool sets, and messages are tagged with agent info for history tracking.
- 🛠️ **Agent-Created Custom Tools** — Agents can now write and register their own reusable tools via `create_tool`/`update_tool`/`delete_tool`. Code is validated, saved to `.crabagent/tools/`, registered immediately, and auto-loads across sessions.
- 🐛 **TUI Queue & History Fixes** — Fixed race condition where queued inputs were sent before previous rendering completed. Fixed message ordering in DB when loading sessions with queued messages via persistence flush improvements.
- 🔤 **TUI CJK & Thinking Fixes** — Fixed CJK character rendering freeze in dual-panel TUI. Fixed thinking text display bugs (off-by-one, cache miss on content update, prefix loss on flush).

**v0.7.2 Highlights**
- 🖥️ **Dual-Panel TUI** — New prompt_toolkit-based full-screen TUI: scrollable output panel (mouse wheel + PageUp/Down/Home/End), persistent input area that auto-grows with content, and real-time status bar. Default mode (`crabagent`), use `--old` for legacy TUI.
- 🖱️ **Mouse Text Selection** — Hold Shift + mouse drag to select text in the output area. Ctrl+C copies to clipboard (macOS pbcopy / Linux xclip).
- 💬 **Interactive Popup Menus** — `/model`, `/sessions`, `/provider` now show scrolling selection popups with arrow key navigation, instead of printing long lists.
- 🧠 **Streaming Thinking** — Agent reasoning (`THINKING_DELTA`) streams in real-time to the output panel, dim italic style.
- 💡 **Completions Menu** — Slash command autocomplete appears as a floating completions menu above the input area.

**v0.7.1 Highlights**
- 📊 **Pipeline Dashboard** — Real-time pipeline visualization: see active pipelines with step progress, agent cards with running counts, and growth charts. History pipelines auto-collapsed.
- 🔄 **AgentRun Persistence** — New `agent_runs` table tracks every agent/pipeline execution with full metadata (tool calls, elapsed time, tokens, iterations). API endpoints for run history and per-agent growth stats.
- 🐛 **Streaming Fix** — `TEXT_DELTA` and `THINKING_DELTA` events are no longer throttled/dropped by SSE forwarder. `TEXT_DONE` handler now uses full text from backend to ensure complete message display.
- 🛠 **Tool Display Fix** — `delegate_parallel` arguments with nested objects no longer show `[object Object]` in the UI.
- 📡 **RunRecorder** — EventBus subscriber that creates `agent_runs` records for pipeline, main, and sub-agent executions in real-time.

**v0.7.0 Highlights**
- 🧠 **Learning quality overhaul** — LLM reflection now extracts **actionable insights** (tool tricks, pitfalls, domain tips), no more "completed in X steps" noise. Failure learning added — agents learn from mistakes too.
- 🌐 **Web proxy support** — `CRAB_WEB_PROXY=http://127.0.0.1:7890` for web_search/web_scrape (critical for users behind firewalls).
- 📊 **Learning Dashboard** — View each agent's task stats and past lessons directly in the Web UI Agent Team panel.
- 📡 **Sub-agent persistence** — Completed sub-agents stay visible in the Dashboard for 30 minutes after finishing.

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

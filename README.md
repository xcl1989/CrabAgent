# 🦀 CrabAgent

> **Your AI Knowledge Work Platform** — Not another coding assistant. A platform where AI agents learn your projects, remember your decisions, and grow with you. Runs in terminal, browser, or desktop.

CrabAgent is a local-first platform for knowledge work. You bring your projects and API keys. It brings a team of AI agents that **remember what you did, learn how you work, and get smarter the more you use them.**

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

**[English](README.md)** | **[中文](README.zh-CN.md)**

---

## Why CrabAgent

Most AI tools are temporary workers — they help with one task, then forget everything. CrabAgent is different:

| What makes it special | What it means for you |
|----------------------|-----------------------|
| **🧠 Project Memory** | It remembers what you did in each project. Open it tomorrow and it picks up where you left off. |
| **📈 Learns your style** | The more you use it, the better it understands your preferences, your code style, your decision patterns. |
| **🤖 AI Team** | Specialized agents (coder, researcher, analyst, writer) that collaborate. Delegate, parallelize, chain into workflows. |
| **🔒 Local-first** | All data stays on your machine. API keys encrypted. No telemetry. No vendor lock-in. |

The difference compounds over time:

```
Day 1:   "It's a helpful AI tool."
Week 1:  "It remembers my project. Nice."
Month 1: "My entire workflow runs through it. Can't go back."
```

---

## Project Memory — The Foundation

Every time you work in a project, CrabAgent automatically extracts lessons and preferences. Next time you open it, it already knows:

```
=== 项目上下文 ===
上次活跃：06-05 15:30
技术栈：Python / FastAPI / SQLAlchemy
项目经验：N+1 查询用 selectinload 优化；API 文档用 OpenAPI 规范
====================
```

This is **not a summary generated on the fly**. It's built from lessons your agents have already learned — zero extra token cost, zero context cache invalidation.

---

## Self-Evolving Agents

Every task teaches your agents something. After each run, they reflect on what worked (and what didn't) and store the insight permanently.

### Dual-engine reflection

```
Agent completes a task
    │
    ├─ Rule engine (instant)
    │   └─ "Too many iterations → break tasks into smaller steps"
    │
    └─ LLM reflection (1-3s)
        ├─ Extracts actionable lessons:
        │   "DuckDuckGo returns fewer Chinese results — use English keywords"
        │   "Prefer web_scrape over web_search for unstable sites"
        ├─ Auto-filters generic praise ("completed in X steps")
        └─ Learns from failures — captures error patterns
```

### Persistent memory layers

| Layer | Scope | What's stored |
|-------|-------|---------------|
| **Project Memory** | Per workspace | Recent lessons, tech stack, activity timeline |
| **User Preferences** | Per user | Communication style, tool preferences, rejected patterns |
| **Agent Lessons** | Per agent | Technical strategies, pitfalls, effective approaches |

### View growth

```bash
# TUI
/agent_stats coder
# → Tasks: 23  Success: 91%  Avg time: 14s
# → Lessons: 18 (rule: 3, LLM: 15)

# Web UI: Agent Team → Learning Stats
```

---

## AI Team

### Built-in agents

| Agent | Role | Best for |
|-------|------|----------|
| **Researcher** | Web researcher | Search, browse, collect data |
| **Analyst** | Data analyst | Compare, identify patterns, generate reports |
| **Coder** | Code expert | Write, review, debug, refactor |
| **Writer** | Content writer | Write, edit, translate, format |
| **Plan Creator** | Task planner | Decompose complex tasks into workflows |

### Orchestration modes

```
Delegate      → @researcher "find competitor pricing"
Parallel      → Run 3 agents simultaneously on different tasks
Pipeline      → research → analyze → write (with data flow)
Handoff       → Pass context from one agent to another
```

### Real-time monitoring

- 🟣 **Running** — step count, elapsed time, tool calls
- 🟢 **Done** — duration, tokens, iterations
- 🔴 **Error** — error summary
- Web: sidebar task board with split-view result comparison

---

## Quick Start

```bash
pip install 'crabagent[serve]'

crabagent init

# TUI — interactive REPL with slash commands
crabagent

# Web UI
crabagent --serve          # → http://localhost:5210

# Single-shot CLI
crabagent "organize this directory"
```

### Desktop App (macOS, development)

Build the Electron wrapper (requires Python + `crabagent` installed on your system):

```bash
# One-command build (from git clone):
make desktop
# → electron/dist-electron/CrabAgent-0.9.4-arm64.dmg

# Or from pip install:
crabagent --build-desktop
```

Or run directly in your browser:

```bash
crabagent --serve          # → http://localhost:5210
```

---

## Features

### 🧠 Project Memory
Remembers your project context across sessions. Zero extra cost.

### 🖼️ Multi-modal
Paste/drop images into conversations. Auto-detects vision model support.

### 🌐 Browser Automation
```bash
pip install 'crabagent[browser]'
playwright install chromium
```
```
> Open https://news.ycombinator.com and show top 5
> Search Google for "Python async", extract results
```

### 🔌 MCP Client
Connect external MCP servers (stdio + HTTP). Tools auto-discover and get prefixed.

### ⏱ Scheduled Tasks
```
> Open Hacker News at 9 AM every day and screenshot top 5
> Check product page every 30 min, notify me if below $500
```

### 🦀 Snapshots (Molt)
Auto-snapshot files before changes. Roll back anytime without Git.
```
/molt rollback <id>
```

### 🔧 Custom Tools
Drop a `.py` file in `.crabagent/tools/` — or let the AI create one for you in a conversation.

---

## Installation

```bash
pip install 'crabagent[serve]'          # CLI + Web UI + API
pip install 'crabagent[browser]'        # Browser automation
pip install 'crabagent[dev]'            # Testing + linting
```

### Development

```bash
make install            # Build frontend + install (editable)
ruff check src/ tests/  # Lint
ruff format src/ tests/ # Format
pytest                   # Run tests
```

---

## CLI / TUI Commands

| Command | Description |
|---------|-------------|
| `/exit`, `/quit` | Exit |
| `/help` | Help |
| `/clear` | Clear context |
| `/model [name]` | Switch model |
| `/models` | List models |
| `/provider [cmd]` | Manage providers |
| `/sessions` / `/session [id]` | List/load sessions |
| `/new` | New session |
| `/agents [cmd]` | Agent team management |
| `/agent [name]` | Switch agent |
| `/agent_stats <name>` | Agent growth stats |
| `/delegate [@agent] [task]` | Delegate task |
| `/memory [list|search|clear]` | Team memory |
| `/skills` / `/skill <name>` | List/view skills |
| `/molt [cmd]` | Snapshot management |
| `/todo [cmd]` | Todo management |
| `/export` | Export as Markdown |
| `/image <path>` | Send image |
| `/runs [agent]` | View run history |
| `/abort` | Abort execution |

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CRAB_DB_URL` | `sqlite+aiosqlite:///./crabagent.db` | Database URL |
| `CRAB_JWT_SECRET` | auto-generated | JWT signing key |
| `CRAB_SERVE_HOST` | `0.0.0.0` | Server host |
| `CRAB_SERVE_PORT` | `5210` | Server port |
| `CRAB_MAX_ITERATIONS` | `50` | Max agent iterations |
| `CRAB_MAX_TOKENS` | `4096` | Max response tokens |
| `CRAB_BROWSER_HEADLESS` | `true` | Browser headless mode |
| `CRAB_WEB_PROXY` | (empty) | HTTP proxy for web tools |

---

## Project Structure

```
CrabAgent/
├── src/crabagent/
│   ├── cli/           # CLI + TUI
│   ├── core/agent/    # Agent loop, tools, compression, agents
│   ├── core/mcp/      # MCP client manager
│   ├── core/          # Database, config, project memory
│   └── serve/         # FastAPI + API + scheduler
├── frontend/          # React SPA
├── electron/          # Electron desktop app
├── scripts/           # Build scripts
├── crabagent.spec     # PyInstaller config
└── crabagent.db       # SQLite database
```

---

## License

GNU Affero General Public License v3 (AGPLv3) for non-commercial use.
Commercial use requires a separate license. Contact the author.

See [LICENSE](LICENSE).

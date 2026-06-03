# 🦀 CrabAgent

> **AI Team Command Center** — Build a team of specialized AI agents that learn and improve over time. Delegate, parallelize, and watch them work in real-time from terminal or browser.

CrabAgent is a local-first AI agent platform. Run it from any project directory via CLI, browser, or native macOS desktop app. Your data stays local, your API keys are encrypted, and you pick any LLM provider.

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
| **🖥️ Desktop App** | Native macOS app via Electron. Auto-starts backend, auto-login, same UI as browser. |
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

### Desktop App (macOS)

```bash
# Build from source:
cd electron && npm install && npm run build:mac
# → electron/dist-electron/CrabAgent-0.9.0-arm64.dmg
```

Double-click `CrabAgent.app` — it auto-starts the Python backend, logs in, and opens the full Web UI in a native window. Requires Python 3.12+ with `crabagent[serve]` installed.

### Installation

### CLI + Web Server

```bash
pip install 'crabagent[serve]'          # CLI + Web UI + API
pip install 'crabagent[browser]'        # Browser automation
pip install 'crabagent[dev]'            # Testing + linting
```

### Desktop App

Clone the repo and build from source (see above). Requires Python 3.12+ with `crabagent[serve]` and Node.js 20+.

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
├── electron/          # Electron desktop app
│   ├── main.js        # Main process (starts Python backend, loads Web UI)
│   ├── preload.js     # Renderer preload
│   └── build/icon.png # App icon
└── crabagent.db       # SQLite database
```

---

## License

GNU Affero General Public License v3 (AGPLv3) for non-commercial use.
Commercial use requires a separate license. Contact the author.

See [LICENSE](LICENSE).

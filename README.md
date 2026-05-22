# 🦀 CrabAgent

> A local AI assistant — CLI + Web dual-mode, MCP support, web search, file operations, custom plugins, and more.

CrabAgent is an AI agent platform that runs from any project directory. It works in your terminal (CLI) or your browser (Web UI), with full access to your local files, tools, and plugins.

---

## Features

| Feature | Description |
|---------|-------------|
| **Dual Mode** | CLI terminal + Web browser, same data |
| **MCP Client** | Connect to external MCP servers (stdio + HTTP), persistent connections with UI management |
| **Web Search & Scrape** | Built-in `web_search` (DuckDuckGo zero-config + SearXNG optional) and `web_scrape` tools |
| **File Operations** | read, write, edit, search, bash execution |
| **Snapshot / Rollback 🦀** | Auto-snapshot before file changes, rollback anytime |
| **Todo List** | Agent-managed tasks, real-time floating widget |
| **Agent Questions** | Agent can ask you questions (with options) |
| **Plugin System** | Write a Python function in `.crabagent/tools/` — it becomes a tool |
| **Multi-Provider** | OpenAI, DeepSeek, Anthropic, and any LiteLLM-compatible provider |
| **Conversation Branches** | Branch from any message, explore different paths |
| **Skill System** | Domain-specific instructions via SKILL.md |
| **Context Compression** | Auto-summarize long conversations |
| **Privacy** | All data stays local, API keys encrypted |

---

## Quick Start

```bash
# Install
pip install 'crabagent[serve]'

# Initialize
crabagent init

# CLI — interactive mode
crabagent

# CLI — single query
crabagent "organize this directory"

# Web UI
crabagent --serve
# → http://localhost:5210
# Default login: admin / xcl1989

# Docker
docker compose up -d
```

---

## Installation

### pip

```bash
pip install 'crabagent[serve]'
```

Optional extras:
- `pip install 'crabagent[serve]'` — Web UI dependencies
- `pip install 'crabagent[dev]'` — Development dependencies (testing, linting)

### From source

```bash
git clone <repo>
cd CrabAgent
make install
```

### Docker

```bash
docker compose up -d
```

---

## CLI Usage

```bash
# Interactive REPL
crabagent

# One-shot query
crabagent "list all files in the current directory"

# Specify provider and model
crabagent -p deepseek -m deepseek-chat "write a Python script"

# Resume a past session
crabagent -s <session_id>

# List available models
crabagent models

# Manage providers
crabagent provider list
crabagent provider add

# Manage skills
crabagent skill list
```

### Interactive Slash Commands

| Command | Description |
|---------|-------------|
| `/exit`, `/quit` | Exit |
| `/help` | Show help |
| `/clear` | Clear conversation context |
| `/history` | Show message count and token estimate |
| `/model [name]` | Switch model |
| `/models` | List available models |
| `/provider [cmd]` | Manage providers |
| `/sessions` | List recent sessions |
| `/session [id]` | Load a session |
| `/new` | Start a new conversation |
| `/molt [cmd]` | List, show, or rollback snapshots |
| `/todo [cmd]` | Manage tasks |
| `/skills` | List available skills |
| `/skill <name>` | Show skill content |

---

## Web UI

Start with `crabagent --serve`, then open `http://localhost:5210`.

- **Login** — Default admin account: `admin` / `xcl1989`
- **Chat** — Send messages, stream responses in real-time
- **MCP Servers** — Add, connect/disconnect, manage MCP servers via UI
- **Web Search** — Built-in `web_search` and `web_scrape` tools (DuckDuckGo by default, configure SearXNG for better results)
- **File Browser** — Browse and preview project files
- **Todo Widget** — Floating task list (bottom-right)
- **Session Management** — Create, switch, delete sessions
- **Provider Management** — Add/configure providers in the UI

---

## MCP (Model Context Protocol)

CrabAgent acts as an **MCP client**, connecting to external MCP servers to extend agent capabilities.

### Supported Transports

- **stdio** — Local subprocess (e.g., `npx -y @mcp/server-filesystem`)
- **HTTP** — Remote MCP servers via Streamable HTTP

### Configuration

Via Web UI (MCP panel) or directly in the database.

MCP tools are automatically prefixed as `mcp__{server}__{tool}` and visually distinguished with a purple icon in the chat.

---

## Web Search

The agent has two built-in web tools:

| Tool | Description |
|------|-------------|
| `web_search` | Search the web. Uses SearXNG if configured, otherwise DuckDuckGo (no API key needed) |
| `web_scrape` | Fetch and extract readable content from any URL |

### SearXNG Setup (Optional)

For better search quality, deploy a SearXNG instance:

```bash
docker run -d --name searxng -p 8888:8080 searxng/searxng
```

Then enable JSON API and configure the URL in Settings (MCP panel → Settings tab).

---

## Custom Plugins

Create a `.py` file in `.crabagent/tools/` and it becomes a tool the agent can call.

### Example: `hello.py`

```python
name = "hello"
description = "Say hello to someone"
parameters = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Name to greet"},
    },
    "required": ["name"],
}
requires_permission = False  # set to True to require confirmation

def run(name: str) -> str:
    return f"Hello, {name}! Welcome to CrabAgent."
```

Both sync (`def run`) and async (`async def run`) functions are supported.

---

## Configuration

Environment variables / `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `CRAB_WORKSPACE` | `cwd` | Workspace directory |
| `CRAB_DB_URL` | `sqlite+aiosqlite:///./crabagent.db` | Database URL |
| `CRAB_JWT_SECRET` | auto-generated | JWT signing key |
| `CRAB_ENCRYPTION_KEY` | auto-generated | Key for API key encryption |
| `CRAB_SERVE_HOST` | `0.0.0.0` | Serve host |
| `CRAB_SERVE_PORT` | `5210` | Serve port |
| `CRAB_AUTO_APPROVE_TOOLS` | `false` | Auto-approve tool execution |
| `CRAB_MAX_ITERATIONS` | `50` | Max agent iterations |
| `CRAB_MAX_TOKENS` | `4096` | Max response tokens |
| `CRAB_MOLT_KEEP_COUNT` | `20` | Number of snapshots to keep |

---

## Project Structure

```
CrabAgent/
├── .crabagent/
│   ├── skills/        # Domain skills (SKILL.md)
│   ├── tools/         # Custom plugin tools
│   └── molts/         # File snapshots
├── src/
│   └── crabagent/
│       ├── cli/       # CLI entrypoint
│       ├── core/      # Agent loop, tools, events, database
│       │   ├── agent/  # Agent context, loop, tool registry
│       │   └── mcp/    # MCP client manager
│       └── serve/     # FastAPI server + API endpoints
├── frontend/          # React SPA
├── crabagent.db       # SQLite database
├── Dockerfile
├── docker-compose.yml
└── Makefile
```

---

## Development

```bash
make install
make build      # Build Python package + frontend
make docker     # Build Docker image
```

---

## License

This project is licensed under the **GNU Affero General Public License v3 (AGPLv3)** for non-commercial use.

For commercial use (internal deployment, SaaS, or any revenue-generating activity), a separate commercial license is required. Please contact the author.

See the [LICENSE](LICENSE) file for details.

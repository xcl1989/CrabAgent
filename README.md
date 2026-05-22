# 🦀 CrabAgent

> A local AI agent platform — CLI + Web dual-mode, MCP client, multimodal (image) support, web search, file operations, custom plugins, and more.

CrabAgent is an AI agent platform that runs from any project directory. It works in your terminal (CLI) or your browser (Web UI), with full access to your local files, tools, and plugins.

---

## Features

| Feature | Description |
|---------|-------------|
| **Dual Mode** | CLI terminal + Web browser, same data |
| **Scheduled Tasks** | Create timed tasks via conversation or Web UI; Agent executes autonomously with notifications |
| **Agent Team** | Multi-agent collaboration: delegate tasks to specialized agents (Researcher, Analyst, Coder, Writer) |
| **Browser Automation** | Playwright-powered headless browser: navigate, click, type, screenshot, extract, scroll |
| **Multimodal (Image)** | Send images via paste, upload, or drag-and-drop; auto vision detection for model compatibility |
| **MCP Client** | Connect to external MCP servers (stdio + HTTP), persistent connections with UI management |
| **Web Search & Scrape** | Built-in `web_search` (DuckDuckGo zero-config + SearXNG optional) and `web_scrape` tools |
| **File Operations** | Read, write, edit, search, bash execution |
| **Snapshot / Rollback 🦀** | Auto-snapshot before file changes, rollback anytime |
| **Todo List** | Agent-managed tasks, real-time floating widget |
| **Agent Questions** | Agent can ask you questions (with options) |
| **Plugin System** | Write a Python function in `.crabagent/tools/` — it becomes a tool |
| **Multi-Provider** | OpenAI, DeepSeek, Anthropic, Google Gemini, and any LiteLLM-compatible provider |
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
- `pip install 'crabagent[browser]'` — Browser automation (Playwright)
- `pip install 'crabagent[dev]'` — Development dependencies (testing, linting)

After installing browser support, install the Chromium browser:
```bash
playwright install chromium
```

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
| `/image <path> [msg]` | Send an image with optional message |

---

## Web UI

Start with `crabagent --serve`, then open `http://localhost:5210`.

- **Login** — Default admin account: `admin` / `xcl1989`
- **Chat** — Send messages, stream responses in real-time
- **Image Support** — Paste from clipboard, click to upload, or drag-and-drop images (max 5 per message, 5MB each)
- **MCP Servers** — Add, connect/disconnect, manage MCP servers via UI
- **Settings** — Configure SearXNG URL and other settings (MCP panel → Settings tab)
- **Web Search** — Built-in `web_search` and `web_scrape` tools (DuckDuckGo by default, configure SearXNG for better results)
- **File Browser** — Browse and preview project files
- **Todo Widget** — Floating task list (bottom-right)
- **Session Management** — Create, switch, delete sessions
- **Provider Management** — Add/configure providers in the UI

---

## Image / Multimodal Support

CrabAgent supports sending images alongside text in both CLI and Web UI.

### Web UI
- **Paste**: Ctrl+V / Cmd+V to paste images from clipboard
- **Upload**: Click the attachment button to select files
- **Drag & Drop**: Drag images directly into the chat
- Images appear as thumbnails before sending and in the chat history

### CLI
```bash
# Send an image with a message
/image /path/to/image.png What's in this image?
```

### Vision Model Detection
CrabAgent automatically detects whether the current model supports vision:
- **Vision models** (Claude 3+, GPT-4o, Gemini, etc.): Images sent as native multimodal content
- **Non-vision models** (DeepSeek, o1-mini, etc.): Images saved to temp files, text placeholder sent to LLM with file path info for MCP tool usage

### Limits
- Max **5 images** per message
- Max **5MB** per image
- Supported formats: PNG, JPEG, GIF, WebP

---

## Browser Automation

CrabAgent can control a headless Chromium browser to interact with web pages, powered by [Playwright](https://playwright.dev/python/).

### Setup

```bash
pip install 'crabagent[browser]'
playwright install chromium
```

> Browser tools are optional — if Playwright is not installed, CrabAgent works normally without them.

### Available Tools

| Tool | Permission | Description |
|------|-----------|-------------|
| `browser_navigate` | Required | Open a URL, return page title, content preview, and screenshot |
| `browser_click` | Required | Click an element by CSS selector or visible text |
| `browser_type` | Required | Type text into an input field, optionally submit the form |
| `browser_screenshot` | Auto | Take a screenshot (viewport or full page), saved to temp file |
| `browser_extract` | Auto | Extract text content from the page or a specific element |
| `browser_scroll` | Auto | Scroll the page up or down by a specified amount |
| `browser_close` | Auto | Close the browser and release resources |

### How It Works

- **Lazy start**: The browser launches on first `browser_navigate` call — no resource overhead until needed
- **Session-scoped**: One browser instance per conversation, shared across all tool calls
- **Auto-cleanup**: Browser closes automatically when the agent finishes or the session ends
- **Headless by default**: Set `CRAB_BROWSER_HEADLESS=false` to run in headed mode (useful for debugging)
- **Inline screenshots**: Browser screenshots automatically appear as images in the chat — no need to open external files
- **Image preview**: Click any image (screenshot or uploaded) to view full-size in a lightbox overlay
- Screenshots are saved to `/tmp/crabagent_screenshots/`

### Example Usage

Ask the agent in natural language:
```
> Open https://news.ycombinator.com and show me the top 5 stories
> Search for "Python async" on Google and extract the results
> Take a screenshot of the current page
```

---

## Scheduled Tasks

CrabAgent can run autonomously on a schedule — you define what to do and when, it executes and notifies you.

### Creating Tasks

**Via conversation** — just tell the Agent:
```
> 每天早上9点打开 Hacker News 把前5条新闻截图给我
> 每30分钟检查一次这个商品页面，价格低于500就通知我
```

The Agent uses `scheduled_task_create` tool and defaults to your current model.

**Via Web UI** — click ⏱ Tasks in the sidebar to create and manage tasks manually.

### Available Tools

| Tool | Description |
|------|-------------|
| `scheduled_task_create` | Create a task with name, question, and cron expression |
| `scheduled_task_update` | Modify an existing task |
| `scheduled_task_delete` | Delete a task |
| `scheduled_task_list` | List all tasks and their status |
| `scheduled_task_pause` | Pause a task |
| `scheduled_task_resume` | Resume a paused task |

### Notifications

- When a scheduled task completes, a notification appears in the notification bell (top-right of the chat header)
- Click the notification to jump to the task's result conversation
- Notifications poll every 30 seconds; unread count shown as a badge

### Task Execution

- **Auto-approve**: Tools run without confirmation (unattended mode)
- **Full capabilities**: Tasks have access to browser, web search, file operations, and MCP tools
- **Result storage**: Each execution creates a new conversation with full message history and screenshots
- **Error tracking**: Failed tasks log error details and notify you

---

## Agent Team (Multi-Agent)

CrabAgent supports multi-agent collaboration — delegate tasks to specialized agents that work independently and report back.

### Built-in Agents

| Agent | Role | Best For |
|-------|------|----------|
| `researcher` 🔍 | Web Researcher | Web search, browsing, data collection |
| `analyst` 📊 | Data Analyst | Data comparison, pattern analysis, reports |
| `coder` 💻 | Code Expert | Code writing, review, debugging, refactoring |
| `writer` 📝 | Content Writer | Writing, editing, translation, formatting |

### Delegate Tasks

The main agent automatically uses `delegate_task` to spawn sub-agents:

```
User: Compare our 3 competitors

Main Agent → delegate_task("researcher", "Browse competitor A and summarize")
Main Agent → delegate_task("researcher", "Browse competitor B and summarize")
Main Agent → delegate_task("analyst", "Compare the findings and write a report")

Each sub-agent runs independently with full tool access
Results are collated by the main agent and presented to you
```

### How It Works

- **Isolated execution**: Each sub-agent has its own context, event bus, and tools
- **Auto-approve tools**: Sub-agents run without user confirmation
- **Event streaming**: Sub-agent progress (text, tool calls, completion) is streamed to the chat
- **Sub-agent cards**: Collapsible cards in the UI show each agent's work
- **No recursion**: Sub-agents can't delegate further (prevents infinite loops)

### Manage Agents

Click 🤖 Team in the sidebar to view and customize agent roles, goals, and models.

---

## MCP (Model Context Protocol)

CrabAgent acts as an **MCP client**, connecting to external MCP servers to extend agent capabilities.

### Supported Transports

- **stdio** — Local subprocess (e.g., `npx -y @mcp/server-filesystem`)
- **HTTP** — Remote MCP servers via Streamable HTTP

### Configuration

Via Web UI (MCP panel) or directly in the database.

MCP tools are automatically prefixed as `mcp__{server}__{tool}` and visually distinguished with a purple icon in the chat.

### Connection Management

- Persistent connections via singleton manager — no subprocess spawn overhead on each request
- Manual reconnect on error — click Reconnect in the UI
- Status polling every 60 seconds

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

Then enable JSON API in SearXNG's `settings.yml`:
```yaml
search:
  formats:
    - html
    - json
```

Configure the URL in **Settings** (MCP panel → Settings tab) or use the "Test Connection" button to verify.

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
| `CRAB_BROWSER_HEADLESS` | `true` | Run browser in headless mode (`false` for headed) |

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
│       │   ├── agent/  # Agent context, loop, tool registry, token limits
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

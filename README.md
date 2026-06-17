# 🦀 CrabAgent

> **AI Knowledge Work Platform** — Chat when you need answers, Work when you need results. Two modes, one seamless experience. Runs in terminal, browser, or desktop.

CrabAgent is a local-first AI platform with **two working modes** that adapt to what you're doing:

| | Chat Mode 💬 | Work Mode 🛠️ |
|---|---|---|
| **Layout** | Session list + conversation | AI sidebar + live workspace |
| **Focus** | Talk, ask, brainstorm | Create, edit, build |
| **Right panel** | — | Document preview / code editor / prototype / meeting notes |
| **Switch** | Click 🛠️ icon in toolbar | Click 💬 icon or AI auto-switches when opening files |

You don't pick a mode upfront. Start chatting, and when the AI starts working on a document or code file, the workspace slides open automatically. Switch back to Chat Mode anytime for a clean conversation view.

```
Chat Mode                          Work Mode
┌──────┬──────────────┐           ┌──┬──────────┬────────────────┐
│      │              │           │  │ AI Chat  │   Workspace    │
│ Sess │  Conversation│           │ 💬│ Sidebar  │  ┌──────────┐  │
│ List │              │           │  │ (350px)  │  │ Document │  │
│      │              │           │  │          │  │ Preview  │  │
│      │              │           │  │ Input    │  │ Code     │  │
│      │              │           │  │          │  │ Prototype│  │
│      │              │           │  │          │  │ Meeting  │  │
└──────┴──────────────┘           │  │          │  └──────────┘  │
                                  └──┴──────────┴────────────────┘
```

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

**[English](README.md)** | **[中文](README.zh-CN.md)**

---

## 💬 Chat Mode — Pure Conversation

The default mode. Session list on the left, full-width conversation on the right. No distractions.

**Best for:**
- Asking questions and getting AI-powered answers
- Brainstorming and exploring ideas
- Quick research via web search and browser automation
- Delegating tasks to specialized AI agents (researcher, analyst, coder, writer)
- Multi-turn conversations with full project memory

```
You: "帮我分析一下这个项目的架构"
AI: [reads files, analyzes patterns, generates structured report]
You: "把分析结果整理成一份 Word 文档"
AI: [creates document] → auto-switches to Work Mode with preview
```

---

## 🛠️ Work Mode — AI + Live Workspace

When the AI creates or opens a file, the interface splits: AI chat shrinks to a 350px sidebar on the left, and the **workspace** takes over the right side. Everything the AI does is visible in real time.

### Workspace types

| Type | What shows | Trigger |
|------|-----------|---------|
| 📄 **Document** | Office document preview (`.docx` / `.xlsx` / `.pptx`) with outline, timeline, and inline edit | AI creates/opens an Office file |
| 💻 **Code** | Monaco-based code editor with syntax highlighting | AI works on a code file |
| 🔬 **Prototype** | Split-pane: source code on left, live preview on right | AI builds an HTML/JS prototype |
| 📝 **Meeting** | Structured meeting notes panel with action item extraction | You click "Start Meeting" |

### Work Mode features

- **Real-time preview**: watch the AI edit a document and see changes reflected instantly
- **Inline editing**: double-click text in document preview to edit directly
- **AI Edit toolbar**: Bold, italic, font size, color — one click to style selected text
- **Natural language edit**: type instructions like "make the heading red" and the AI applies it
- **Document timeline**: see the full history of AI operations on the document
- **File browser**: browse project files without leaving Work Mode
- **One-click switch back to Chat Mode** when you're done

```
Work Mode in action:

You: "读取 sales.xlsx 汇总 Q1 数据，做成一份报告"
                          │
  ┌───────────────────────┼───────────────────────────────┐
  │  AI Chat Sidebar      │  Workspace (Document Preview) │
  │                       │                               │
  │  AI: Reading file...  │  ┌─────────────────────────┐  │
  │  AI: Q1 total: $1.2M  │  │  Q1 Sales Report        │  │
  │  AI: Creating doc...  │  │  ───────────────        │  │
  │  AI: Done! ✓          │  │  Total: $1.2M           │  │
  │                       │  │  Growth: +23%           │  │
  │  [Input: continue...] │  │  ...                    │  │
  │                       │  └─────────────────────────┘  │
  └───────────────────────┴───────────────────────────────┘
```

---

## 🤖 AI Team

Both modes have access to a team of specialized agents:

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

---

## 📬 Email Intelligence — Tasks from Inbox

CrabAgent watches your inbox and turns emails into action items — automatically.

```
Incoming email: "明天下午3点开会讨论新功能"
      │
      ├─ 🧠 LLM analyzes: meeting + deadline detected
      ├─ 📝 Drafts a reply for your review
      ├─ ✅ Creates task: "参加关于crabagent的会议" (due tomorrow 3PM)
      └─ 🔗 Links task to email conversation — click to view full context
```

No rules, no regex. Just LLM-powered understanding.

---

## 💬 WeChat Channel — AI in Your Pocket

Bind your WeChat account via QR code, and CrabAgent becomes reachable from your phone.

```
You (WeChat): "看一下26年1月有啥工作"
       │
       ├─ 🤖 Agent processes with full project context
       ├─ 💬 Replies directly in WeChat chat
       └─ 🔔 Pushes notifications: task overdue, scheduled task done, email summary
```

**Three modes:**
- **Command execution** — send instructions from WeChat, Agent executes and replies
- **Proactive notifications** — task deadlines, scheduled task results, email summaries auto-pushed
- **Conversational** — multi-turn chat with full project memory

---

## 🧠 Project Memory & Self-Evolving Agents

Every time you work in a project, CrabAgent automatically extracts lessons and preferences. Next time you open it, it already knows:

```
=== 项目上下文 ===
上次活跃：06-05 15:30
技术栈：Python / FastAPI / SQLAlchemy
项目经验：N+1 查询用 selectinload 优化；API 文档用 OpenAPI 规范
====================
```

After each task, agents reflect on what worked (and what didn't) and store the insight permanently:

| Layer | Scope | What's stored |
|-------|-------|---------------|
| **Project Memory** | Per workspace | Recent lessons, tech stack, activity timeline |
| **User Preferences** | Per user | Communication style, tool preferences, rejected patterns |
| **Agent Lessons** | Per agent | Technical strategies, pitfalls, effective approaches |

---

## Quick Start

```bash
pip install crabagent
crabagent init

# TUI — interactive REPL with slash commands
crabagent

# Web UI — Chat Mode & Work Mode
crabagent --serve          # → http://localhost:5210
                           #   Default login: admin / xcl1989

# Single-shot CLI
crabagent "organize this directory"
```

### Desktop App (macOS, development)

Build the Electron wrapper (requires Python + `crabagent` installed on your system):

```bash
# One-command build (from git clone):
make desktop
# → electron/dist-electron/CrabAgent-0.10.5-arm64.dmg

# Or from pip install:
crabagent --build-desktop
```

---

## Features

### 🛠️ Work Mode
Split-pane workspace with live document preview, code editor, prototype builder, meeting notes, and Markdown editor. AI chat sidebar stays interactive while you work.

### 📝 Markdown Editor
Split-pane editor for `.md` files — source on the left, live rendered preview on the right. Bidirectional scroll sync, GFM tables, syntax-highlighted code blocks. Switch between Source / Split / Preview views.

### 📄 Intelligent Document Processing
AI agents can read, create, edit, and preview Office documents (`.docx`, `.xlsx`, `.pptx`) directly in conversations.

### 🧠 Project Memory
Remembers your project context across sessions. Zero extra cost.

### 🖼️ Multi-modal
Paste/drop images into conversations. Auto-detects vision model support.

### 🌐 Browser Automation
```bash
pip install 'crabagent[browser]'
playwright install chromium
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

### 🔧 Custom Tools
Drop a `.py` file in `.crabagent/tools/` — or let the AI create one for you in a conversation.

---

## Installation

```bash
pip install crabagent                    # CLI + Web UI + API (all-in-one)
pip install 'crabagent[browser]'        # Browser automation
pip install 'crabagent[memory]'         # Semantic memory search (recommended)
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
| `CRAB_MEMORY_EMBEDDING` | `auto` | Memory vector search: `auto` / `on` / `off` |

---

## Project Structure

```
CrabAgent/
├── src/crabagent/
│   ├── cli/           # CLI + TUI
│   ├── core/agent/    # Agent loop, tools, compression, agents
│   ├── core/mcp/      # MCP client manager
│   ├── core/          # Database, config, project memory, embedding
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

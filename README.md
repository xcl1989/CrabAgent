# 🦀 CrabAgent

**A local-first AI work assistant for conversations, files, browsers, and the desktop.**

English | [中文](README.zh-CN.md) · [Python 3.12+](https://www.python.org/downloads/) · [License](LICENSE)

CrabAgent brings AI chat, task execution, and a live workspace together. Ask an agent to research a question, edit code or Office documents, navigate a browser, or operate an authorized native macOS app. Use Chat Mode for discussion and Work Mode to inspect documents, code, and prototypes as you work.

## Highlights

- **Chat and workspace**: multiple conversations and workspaces, with Markdown, code editing, document preview, and prototypes. Responses can include Mermaid diagrams, charts, and KPI cards.
- **Agent team and project memory**: delegate research, analysis, coding, or writing when useful; run parallel tasks or pipelines, hand off work, and retain project knowledge and preferences across sessions.
- **Goals and tasks**: track objectives, acceptance criteria, and progress alongside tasks, calendars, scheduled jobs, and meeting action items.
- **Files and documents**: work with local files and create, edit, or preview Word, Excel, and PowerPoint documents. Snapshots support rollback.
- **Browser and macOS control**: the collaboration browser shares login state; opt-in macOS control operates allowlisted native apps. You handle CAPTCHA, MFA, and other human-only steps.
- **Integrations**: MCP, custom tools, email, WeChat, remote access through Tailscale, and task notifications via Bark or ntfy are available with their respective configuration.
- **Project collaboration**: editing intentions are advisory; shared files show current intentions and saved changes, while version checks prevent stale saves.

## Two Work Modes

| | Chat Mode | Work Mode |
|---|---|---|
| Best for | Questions, discussion, search, and planning | Creating or changing files while inspecting results |
| Layout | Session list and conversation | AI sidebar with a document, code, or prototype workspace |
| Typical actions | Switch models, use tools, delegate to agents | Preview Office files, edit Markdown, inspect code and meeting notes |

Switch modes in the interface; opening or creating a file can also bring up the workspace. The conversation remains available throughout.

**For example**, ask an agent to summarize a spreadsheet and create a report, or inspect a codebase, explain changes, and run tests. Check sources and results when working with real business data.

## Quick Start

Requires Python 3.12 or later.

```bash
pip install crabagent
crabagent init

crabagent                         # interactive TUI
crabagent --serve                 # Web UI: http://localhost:5210
crabagent "organize this directory"  # single CLI request
```

Configure a model provider when prompted, or use Settings for ChatGPT subscription login, MCP, and other integrations. Optional browser automation dependencies:

```bash
pip install 'crabagent[browser]'
playwright install chromium
```

The Web server listens on `0.0.0.0:5210` by default and may be reachable from other devices. Review authentication, network access, and firewall settings before remote use.

## Desktop App

The desktop app supports macOS and Windows. After installing CrabAgent, build it with:

```bash
crabagent --build-desktop
```

From source, use `make desktop` on macOS or `scripts/build-desktop.ps1` on Windows. The desktop app also includes an optional status pet controlled from the tray or app menu.

## Agent Team, Goals, and Memory

Built-in agents include a researcher, data analyst, coding expert, writer, and planner. Choose a role in conversation or let the agent delegate, run independent work in parallel, or connect steps in a pipeline. For straightforward tasks, the current agent can work alone.

Goal Mode tracks ongoing work: use the target button or `/goal <objective>` to create a goal with acceptance criteria, constraints, and checkpoints. Pause, resume, or inspect progress as needed. Auto Continue is bounded by the goal state and configured budgets.

Project memory retains workspace context, shared knowledge, preferences, and lessons for later sessions. Use the task board, calendar, and scheduled tasks for ongoing work; meeting notes can be used to extract action items.

## Browser and Desktop Control

The **collaboration browser** shares its embedded browser login state with you. An agent can navigate, fill non-sensitive fields, and inspect pages; you handle logins, CAPTCHA, and MFA. Sensitive input and high-risk actions remain subject to safeguards.

**macOS control** is opt-in and requires application authorization. Grant Accessibility and Screen Recording permissions when prompted; the agent can inspect windows and controls and use keyboard and mouse input in allowed apps. Availability depends on the operating system and target application.

## Project Collaboration and Safety

Conversations belonging to the same user can share collaboration records. A session with an explicit valid workspace can automatically join its project; unlinking opts the session out. An editing intention describes a file or directory and what you plan to change. Overlap is shown but never blocks editing. File reads and editor panels show relevant intentions and saved-change summaries, with text diffs available on demand. Managed saves check the version and reject stale writes; reread before reapplying a change. Sessions without a project do not send project collaboration tools to the model.

This is **cooperative coordination, not an operating-system file lock**. Bash no longer automatically claims the entire working directory, but shell commands, background processes, and external editors are not forcibly excluded from writing; version checks detect only some external changes. Records are isolated by user, not shared across accounts.

## Remote Access and Integrations

- **Remote access**: use a controlled network such as Tailscale to reach the Web UI. Check the listening address, authentication, and firewall rules first; do not expose the service directly to the public internet.
- **Notifications and channels**: configure Bark or ntfy in Settings for task events. WeChat and email integrations require separate configuration and authorization.
- **Extensions**: connect MCP servers in Settings or add custom tools under `.crabagent/tools/`. Configure tool and external-service permissions for your use case.

## Configuration and Commands

Environment variables use the `CRAB_` prefix and can be supplied through the environment or `.env`. Model providers and integrations can also be managed in Settings.

| Setting | Default | Purpose |
|---|---|---|
| `CRAB_SERVE_HOST` / `CRAB_SERVE_PORT` | `0.0.0.0` / `5210` | Web server listening address and port |
| `CRAB_DB_URL` | SQLite URL for `~/.crabagent/crabagent.db` | Database connection |
| `CRAB_MAX_ITERATIONS` / `CRAB_MAX_TOKENS` | `200` / `16384` | Agent iteration and response token limits |
| `CRAB_WEB_PROXY` | empty | Proxy for web search and scraping |

Use `/help` in the TUI to list commands. Common commands include `/model`, `/sessions`, `/new`, `/agents`, `/memory`, `/skills`, `/molt`, and `/todo`.

## Development

```bash
make install                  # build the frontend and install in editable mode
ruff check src/ tests/
pytest tests/

cd frontend && npm run build  # build the frontend
```

Key directories: `src/crabagent/core/` (agent and core services), `src/crabagent/serve/` (API), `frontend/` (web UI), and `src/crabagent/electron/` (desktop app).

## License

Non-commercial use is covered by AGPL-3.0; commercial use requires a separate license. See [LICENSE](LICENSE) for the full terms.

# Changelog

All notable changes to CrabAgent are documented in this file.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

中文版本：[CHANGELOG.zh-CN.md](CHANGELOG.zh-CN.md)

---

## [0.9.9]

### Added
- **Email Smart Task Extraction** — LLM analyzes incoming emails and auto-creates tasks from meetings, deadlines, and action items
- **Task-Conversation Linking** — tasks created from emails link back to the original email conversation; click "查看详情" from the task panel
- **Rich Email Notifications** — notification panel now shows email content preview, reply draft, and auto-created tasks with expand/collapse for long content

### Fixed
- **Task API routing** — `task_router` was imported but never mounted; tasks were invisible in the frontend panel
- **Task extraction `datetime` import** — missing import caused silent failure in email task extraction
- **Notification display** — replaced single-line truncation with line-clamp + expand/collapse for long email content

### Changed
- Version bumped to 0.9.9

---

## [0.9.6]

### Added
- **i18n multi-language support** — English + Chinese (中文) with per-session language switching
- Language preference persistence across sessions
- Locale mismatch detection and rebuild prompt

### Fixed
- Language switch now properly updates `User.locale` and `AppSetting`
- Console error logging for language switch failures

---

## [0.9.5]

### Added
- **pip-installable desktop build** — `crabagent --build-desktop` from pip install
- Electron source files included in wheel

### Changed
- README updated with `--build-desktop` usage

---

## [0.9.4]

### Added
- **Desktop build pipeline** — `make desktop` builds PyInstaller binary + Electron .dmg in one command
- **Memory page** — dedicated UI for browsing/editing/searching project memory, agent lessons, user preferences
- **LLM-based dedup** — prevent duplicate lessons and preferences at extraction time
- **ChatInput component** — extracted input area to fix re-render lag with many messages

### Changed
- **UI navigation** — removed Dashboard, added Memory tab; Agents page enhanced with stats + recent runs
- **Desktop app packaging** — new `scripts/build-desktop.sh` one-command build
- **Version** — bumped to 0.9.4

### Fixed
- **grep tool** — switched from glob to os.walk with pruning, added ignore_dirs, max_depth, file limit
- **Duplicate memory entries** — lesson/preference keys now use content hash instead of timestamp
- **Agent lessons explosion** — LLM-based dedup at extraction time
- **MemoryPage layout** — only list scrolls, tabs and search bar stay fixed

---

## [0.9.1]

### Added
- **Full sub-agent content persistence** — tool calls and results from sub-agents are now saved to DB (`detail` field in sub_agent message JSON), allowing full content display after page refresh
- **Agents page redesign** — left-right split layout: compact agent list on the left, detail/edit panel on the right, with learning stats embedded
- **Page tab persistence** — replaced `react-router-dom` `<Routes>` with state + CSS `hidden`, so ChatPage state survives tab switches to Dashboard/Agents

### Changed
- **User message bubble max-width** — reduced from 720px to 520px for better CJK line breaking
- **Sidebar footer layout** — 3 tool buttons (MCP, Tasks, API Keys) now arranged horizontally instead of 2x2 grid
- **AgentBar display name** — shows full display name instead of first word only
- **Removed `react-router-dom`** dependency from production bundle (reduced vendor-react chunk from 49KB to 0.03KB)

### Fixed
- Sub-agent content not visible after page refresh — `subAgentContents` map now populated from DB on load
- Missing `sub_agent_id` on DB-loaded sub-agent messages — generates stable `db-sub-${id}` keys
- `scrollbar-none` CSS class undefined — added definition for both WebKit and Firefox
- Hardcoded Chinese string in image fallback prompt — changed to English
- Undefined `--accent-2-border` CSS variable reference — removed fallback, uses `--border` directly
- AgentsPage flashing "No agents" before load — added loading spinner state
- Inconsistent page header heights — all standardized to `h-12`
- `shadow-lg` raw Tailwind class — replaced with `shadow-[var(--shadow-lg)]` design token
- Learning stats grid overflow on small screens — changed to `grid-cols-2 sm:grid-cols-4`

### Removed
- Sidebar "Team" button — duplicated Agents page tab, now only accessible via top nav
- `AgentTeamPanel.tsx` — logic consolidated into `AgentsPage.tsx`

---

## [0.9.0]

### Added
- **Electron desktop app** — native macOS app with auto-start Python backend, auto-login, and system tray support
  - `electron/` directory with `main.js` / `preload.js` / `electron-builder` config
  - `crabagent-gui` entry point replaced by Electron (older PySide6 GUI removed)
  - macOS `.app` + `.dmg` build via `npm run build:mac`
  - Crab emoji (`🦀`) app icon rendered with native macOS CoreText
- **Multi-workspace support** — filter sessions by workspace directory
  - `GET /api/sessions?workspace=` query parameter
  - `GET /api/sessions/workspaces` endpoint — lists workspaces with session counts
  - `WorkspaceSwitcher` component in Web UI with directory picker (no more manual path entry)
  - `list_conversations()` service layer supports `workspace` filter
- **Global database migration** — `crabagent.db` auto-migrates from CWD to `~/.crabagent/` on first launch
  - `_migrate_db_to_home()` in `init_db()` detects old DB and copies it
  - `db_url` now defaults to `~/.crabagent/crabagent.db` via `model_post_init`

### Changed
- **Auth refactor** — `hash_password` / `verify_password` extracted to `core/auth_utils.py` for shared use
- **Mobile responsiveness** — NavBar icon-only on small screens, TaskBoard as bottom drawer, compact ChatPanel/InputBar
- **SSE reconnection fix** — `useSSE.ts` handles `"message_created"` event type properly

### Fixed
- Electron app window auto-closing on launch (removed `titleBarStyle: hiddenInset`, improved lifecycle)
- `QFileSystemModel` import correction (moved from `QtGui` to `QtWidgets`)

### Removed
- PySide6 GUI module (`src/crabagent/gui/`) — replaced by Electron
- `gui` optional dependencies (`PySide6`, `qasync`, `markdown2`)

---

## [0.8.1]

### Added
- **Long-term memory middleware framework** (`core/agent/middlewares/`)
  - `Middleware` protocol with `on_conversation_start` / `before_llm_call` / `on_conversation_end` hooks
  - `MiddlewareChain` runner with graceful error isolation per middleware
  - Three built-in middlewares: `CompressMiddleware`, `ReflectMiddleware`, `TitleMiddleware`
- **Main-loop auto-reflection** — the main agent now extracts lessons and user preferences after every conversation (previously only sub-agents did)
  - Rule-based + LLM-based lesson extraction
  - New `llm_extract_user_preferences()` — Lobehub-style behavioural preference mining (up to 3 prefs per conversation)
  - Persisted to `AgentMemory` table with `memory_type ∈ {agent_lesson, user_preference}`
- **Query-aware memory recall** — `build_memory_prompt(user_id, query=...)` now keyword-searches both team knowledge and past lessons relevant to the current user message and injects them into the system prompt
- **Per-agent lesson injection for the main agent** — new `inject_agent_lessons()` shared by both main loop and sub-agent delegation
- **Auto-title middleware** — first exchange of a fresh conversation is summarised into a 4-8 word title via a cheap LLM call; persisted to `conversations.title` with `auto_titled=1` flag (new column)
- **DOM-aware browser tool** — `browser_navigate` / `browser_click` / `browser_type` / `browser_scroll` now inject `data-crab-idx` attributes on every visible interactive element and return a numbered list (`[1] a "Sign in"`, `[2] input[email]`, …)
- **`browser_click_index` tool** — click by `[N]` index instead of guessing CSS selectors; far more reliable than the legacy `browser_click(selector=...)`
- **Vision screenshot embedding** — when the active model supports vision, browser tool results include base64 `image_url` blocks so the LLM literally sees the page; non-vision models still get the text preview + a path hint
- **Screenshot history rolling** — `BrowserManager` keeps the last N (default 3) screenshots to bound context size; oversized images (>200KB) auto-skip embedding
- New settings: `memory_auto_extract`, `memory_auto_recall`, `memory_max_inject`, `browser_strategy`, `browser_screenshot_to_llm`, `browser_screenshot_history`, `browser_screenshot_max_bytes`

### Changed
- Refactored `core/agent/agents.py` — `_classify_task` / `_rule_extract_lesson` / `_llm_reflect_lesson` moved to a new `core/agent/reflect.py` module; both sub-agent delegation and main-loop middleware share the same reflection logic
- Sub-agent lesson injection in `spawn_sub_agent` now delegates to the shared `inject_agent_lessons()` helper (no behaviour change)
- `loop.py` tool result handling now supports `str | list[dict]` (multimodal); list content is JSON-serialised on persistence and rehydrated on read
- `_build_messages` path in the loop now consults `MiddlewareChain.run_before_llm` when present (compress middleware), with a fallback to direct `compress_context` for contexts without middlewares attached

### Fixed
- Long-standing inline `loop.py` compression call now goes through the middleware chain when attached, enabling consistent pre-LLM hooks
- `prompt.py` now passes `query` to `build_memory_prompt` so first-message recall works

---

## [0.8.0]

### Added
- Complete Web UI redesign with new CrabAgent ocean-teal design system; full light + dark theme support with auto-detection of system preference
- Token-based design foundation — no more hardcoded hex values
- Reusable UI component library under `frontend/src/components/ui/`: Button, Input, Modal, ConfirmDialog, Toast (sonner), Tooltip (Radix), EmptyState, LoadingState, Skeleton, CodeBlock with copy + syntax highlighting
- `useThemeColors()` hook for recharts SVG strokes that automatically follow the active theme
- Mobile-responsive layout: SessionList becomes a slide-in drawer on `<md` viewports, hamburger menu button in the ChatPage toolbar (mobile only)
- AgentsPage promoted from modal overlay to dedicated inline page at `/agents`; ChatPage retains modal mode for quick access

### Changed
- Vite `manualChunks` splits vendor code into 4 chunks (react / charts / markdown / ui); largest chunk reduced from 1.22 MB to 380 kB
- DashboardPage replaces 44 inline styles and `AGENT_THEME` hardcoded hex gradients with theme-aware `agentColor()` helper + `--agent-*` CSS variables; Lucide icons replace ASCII glyphs
- TodoWidget, McpStatusBar, FileBrowser, TaskBoard refactored to use design tokens and Lucide icons

---

## [0.7.4]

### Added
- Session Agent switching — `/agent` (TUI) or `POST /api/sessions/{id}/agent` (API) switches the current agent identity mid-session; tool whitelist and model override follow the agent profile, all messages tagged with agent info for history tracking
- Agent-created custom tools — agents can write and register reusable tools via `create_tool` / `update_tool` / `delete_tool`; code is validated, saved to `.crabagent/tools/`, registered immediately, auto-loads across sessions

### Fixed
- TUI queue + history race condition where queued inputs were sent before previous rendering completed
- Message ordering in DB when loading sessions with queued messages
- TUI CJK character rendering freeze in dual-panel mode
- TUI thinking text display bugs (off-by-one, cache miss on content update, prefix loss on flush)

---

## [0.7.2]

### Added
- Dual-panel TUI based on prompt_toolkit: scrollable output panel (mouse wheel + PageUp/Down/Home/End), auto-growing input area, real-time status bar. Default mode (`crabagent`); `--old` for legacy TUI
- Mouse text selection: Shift + drag to select output text; Ctrl+C copies to clipboard (macOS pbcopy / Linux xclip)
- Interactive popup menus for `/model`, `/sessions`, `/provider` with arrow-key navigation
- Streaming thinking — `THINKING_DELTA` events render in real-time, dim italic style
- Slash command autocomplete as a floating completions menu above the input area

---

## [0.7.1]

### Added
- Pipeline dashboard — real-time pipeline visualisation with step progress, agent cards with running counts, growth charts; historical pipelines auto-collapsed
- `agent_runs` table tracks every agent / pipeline execution with full metadata (tool calls, elapsed, tokens, iterations); API endpoints for run history and per-agent growth stats
- `RunRecorder` — `EventBus` subscriber that creates `agent_runs` records for pipeline, main, and sub-agent executions in real-time

### Fixed
- `TEXT_DELTA` and `THINKING_DELTA` events no longer throttled/dropped by the SSE forwarder
- `TEXT_DONE` handler now uses full text from backend to ensure complete message display
- `delegate_parallel` arguments with nested objects no longer render `[object Object]` in the UI

---

## [0.7.0]

### Added
- Learning quality overhaul — LLM reflection now extracts actionable insights (tool tricks, pitfalls, domain tips); no more "completed in X steps" noise
- Failure learning — agents learn from mistakes too
- Web proxy support — `CRAB_WEB_PROXY=http://127.0.0.1:7890` for `web_search` / `web_scrape`
- Learning dashboard — view each agent's task stats and past lessons in the Web UI Agent Team panel
- Sub-agent persistence — completed sub-agents remain visible in the dashboard for 30 minutes after finishing

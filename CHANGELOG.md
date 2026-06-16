# Changelog

All notable changes to CrabAgent are documented in this file.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

中文版本：[CHANGELOG.zh-CN.md](CHANGELOG.zh-CN.md)

---

## [0.10.4]

### Added
- **Calendar Day View — Event Layer Separation** — time-spanning events (with end_time) and time-point reminders (task deadlines, events without end_time) are now visually distinct
  - **Block events** (meetings, timed tasks): rendered as coloured blocks on the timeline, unchanged
  - **Pin events** (reminders, deadlines): rendered as floating red labels on the right side of the timeline, positioned precisely at the trigger time-point with `translateY(-50%)`
  - **Automatic layout**: block events shrink their right edge (150px) when pin events exist, preventing overlap
  - **Minimum block height**: raised from 24px to 36px for better readability of short events
  - Backend untouched — pure frontend change in `DayView` component

---

## [0.10.3]

### Fixed
- **WeChat Image Reception** — images sent by WeChat users are now correctly received, decrypted, and processed by the Agent
  - **AES key format bug**: iLink returns the key in `media.aes_key` as base64(hex_string) — a double encoding that `_normalize_key` could not parse, falling back to MD5 and producing garbage decryption. Fixed by adding a base64-of-hex decode path in `crypto.py` and preferring the top-level `aeskey` field (plain hex) in `download_media()`
  - **Image handling for non-vision models**: when the default model cannot process `image_url` content blocks, images are now saved to a local file with a text hint guiding the Agent to use any available vision tool (e.g. MCP image analysis). System prompt updated to instruct the Agent to self-discover image analysis capabilities
  - **Image dimension display**: `[图片 0x0]` placeholder replaced with `[图片]` when width/height are unavailable (iLink does not return these fields for images)

### Added
- **WeChat Conversation Archival** — automatic rollover of long WeChat conversations to prevent unbounded context growth
  - **Date trigger**: when a conversation's creation date is before today, it is archived after the user's reply is sent
  - **Volume trigger**: when prior messages exceed 150, archived as a safety net
  - **Summary injection**: old conversation is LLM-summarized (≤5000 chars), old conversation renamed to `(已归档 MM-DD HH:MM)`, new conversation created with the summary injected as initial context
  - **Zero perceived latency**: archival runs asynchronously after the reply is delivered; user never waits
  - **Graceful degradation**: if LLM summarization fails, archival is skipped and retried on the next trigger

---

## [0.10.2]

### Added
- **WeChat Channel (iLink Bot)** — full two-way WeChat integration via Tencent's iLink Bot API
  - QR code login, async long-poll message loop (35s), AES-128-ECB media encryption
  - Auto-reply to incoming WeChat messages through the Agent (with multi-turn conversation memory)
  - Configurable workspace per WeChat channel; conversations tagged with `source='wechat'` for isolation
  - REST API: `GET /api/wechat/status`, `POST /api/wechat/qrcode`, `PUT /api/wechat/config`, `POST /api/wechat/test`, `GET /api/wechat/conversations`
  - Frontend `WeChatPanel` with binding status, workspace selector, notification toggles, and conversation history
- **WeChat Notification Sync** — system notifications (scheduled task results, email summaries, email polling alerts) now auto-push to WeChat
  - Per-category toggles: task overdue, scheduled task result, email summary
  - `context_token` persistence: push target and token auto-saved on first incoming message, restored on service restart
  - Email context injection: when an email notification pushes to WeChat, the email details (sender, subject, body, draft) are injected into the WeChat conversation as context, so the user can say "reply to the email" and the Agent has full context
- **Settings Page Tab Layout** — reorganized from single-page scroll into three tabs: General / Search / WeChat
  - WeChat panel consolidated from 5 cards to 3: Account (binding + workspace + auto-reply), Notifications (toggles + push target), Conversation History (collapsible)
  - Save button only shown on General/Search tabs (WeChat settings are instant-save)

### Changed
- `_create_notification()` now accepts `category` parameter for WeChat push routing
- `WeChatNotification.send()` falls back to persisted `notify_target_user` + `cached_context_token` when memory `_context_store` is empty
- `WeChatMessageLoop.start()` restores persisted context tokens into memory cache on startup

### Fixed
- WeChat notifications silently failing with "No target user_id and no cached users" — push target now auto-persisted from first incoming message
- Email-to-WeChat context gap: user says "reply to email" in WeChat but Agent has no email context — context now injected into WeChat conversation
- Duplicate `Globe` icon for General and Search sections — replaced with `SlidersHorizontal` and `Search` icons

## [0.10.1]

### Added
- **Document Quick Edit** — double-click text in document preview to edit inline, with paragraph splitting on Enter
  - Backend `POST /api/documents/quick-edit/text` endpoint: plain text replacement (no newlines) or split paragraph into multiple paragraphs (with newlines)
  - Frontend injects editing script into preview iframe: double-click → contenteditable → click outside to save / Escape to cancel
  - Preview HTML gets `white-space: pre-wrap` CSS injected to render `\n` as visible line breaks
  - Automatic backup to `~/.crabagent/docs-backup/` before each edit

### Fixed
- `NameError: name 'json' is not defined` — added missing import

## [0.10.0]

### Added
- **Semantic Memory Search** — memory recall upgraded from SQL `LIKE` keyword matching to vector similarity search using `sentence-transformers`
  - New `MemoryEmbedding` table stores 384-dim float32 vectors (base64-encoded) for each memory entry
  - `agent_memory_search_vector()` computes cosine similarity × 0.7 + importance × 0.3 for ranking
  - Automatic fallback to LIKE search when `sentence-transformers` is not installed
  - `CRAB_MEMORY_EMBEDDING` env var controls behavior: `auto` (default) / `on` / `off`
  - New optional dependency: `pip install 'crabagent[memory]'`
- **Cross-Agent Lesson Sharing** — agents can now reuse high-quality lessons from other agents
  - When an agent's own lessons < 5, supplements with lessons from other agents where importance ≥ 0.7 and similarity ≥ 0.4
  - Enables knowledge transfer across the team (e.g., coder benefits from researcher's search strategies)
- **Memory Quality Decay** — weekly cron job automatically prunes stale memories
  - Every Monday 03:00: memories with `access_count=0` and age > 30 days get importance reduced by 0.1
  - Memories with importance < 0.2 and age > 60 days are deleted
- **Data Cleanup** — reduced memory entries from 645 → 530 (removed duplicates, low-quality entries, stale project docs)
- **Bash Streaming Output** — bash tool now streams output in real-time via SSE instead of blocking until completion
  - New `BASH_OUTPUT` / `BASH_EXIT` event types for live terminal-style display
  - Auto-background on timeout with log file path for follow-up
  - Frontend: terminal-style panel with green monospace text and pulsing indicator
- **Office Tool Fixes** — `office_read` now supports `offset` parameter; `add_element` supports `index`/`after`/`before` positioning; `office_query` auto-truncates output over 50K chars
- **Intelligent Document Processing** — AI agents can now read, create, edit, query, and render Office documents (`.docx`, `.xlsx`, `.pptx`) through five built-in tools: `office_read`, `office_create`, `office_edit`, `office_query`, `office_render`
  - Backend: `OfficeManager` wraps the OfficeCLI binary for document operations
  - Frontend: `DocumentPanel` with resize handle, maximize/restore button, and drag overlay (prevents iframe mouse-event hijacking)
  - Frontend: `DocumentPreview` with file-type icons, loading/error states, and HTML preview
  - SSE events for real-time document operation visualization: `doc_op_start`, `doc_op_delta`, `doc_op_preview`, `doc_op_done`
- **Scrapling integration for web scraping** — `web_scrape` now uses [Scrapling](https://github.com/D4Vinci/Scrapling) parser for high-quality structured HTML extraction
  - Headings → Markdown headers, `<p>` → paragraphs (with inline links), `<li>` → lists, `<tr>` → tables, `<a>` → `[text](url)`
  - New `selector` parameter for CSS-selector-based element extraction
  - Automatic noise filtering (script, style, nav, footer, sidebar, etc.)
  - Graceful fallback to lxml when Scrapling is unavailable
- **Session agent persistence** — loading a historical session now restores the last-used agent profile
  - Backend: `agent` field added to `SessionResponse`
  - Frontend: agent restored on auto-load, session select, and new session
- **Context compression quality fix** — compression summaries no longer truncated mid-sentence
  - Prompt changed from "200-500 words" to "comprehensive, no length limit, use Markdown"
  - `max_tokens` increased: 1024 → 4096
  - Input truncation relaxed: tool results 500→2000 chars, messages 1000→3000 chars

### Changed
- **Document panel layout** — default width 480→520px, dynamic max-width calculation, chat content no longer squeezed when document panel is open
- **Univer dead code cleanup** — removed `UniverEditor.tsx`, `@univerjs/*` dependencies, orphaned i18n keys, and "在线编辑" button (open-source Univer cannot import/edit existing Office files)
- **FileBrowser** — Git and Molts sections default to collapsed
- **DocumentPreview** — optimized loading/error states, type-specific file icons
- **Memory search** — `build_memory_prompt()`, `inject_agent_lessons()`, and `memory_recall` tool now use vector search with LIKE fallback
- **Team memory type fix** — fixed `team` memories never being injected (was querying `team_knowledge` instead of `team`)

### Fixed
- Document panel drag handle: iframe stealing mouse events during drag — fixed with transparent overlay
- Maximize button: couldn't restore after maximizing — fixed parent container positioning
- Chat content squeezed when document panel maximized — dynamic maxWidth calculation
- `office_read` always returning from paragraph 1 — added `offset` parameter
- Bash tool hard-coded 8s timeout cutting off normal commands — replaced with streaming + auto-background

---

## [0.9.9.post1]

### Added
- **Token Usage Tracking** — new `TokenUsage` DB model, aggregation API (`/api/token-usage/*`), and frontend `UsagePage` with daily/hourly trends, by-agent/by-model distribution, cache hit rate
- **Context Compression Streaming** — compression summary now streams token-by-token via SSE (`compress_start` / `compress_delta`), frontend renders an inline card with real-time text
- **MCP Server Edit** — MCP panel now supports editing existing servers (name, transport, command, args, env, headers) with a pencil icon
- **GLM-5 Model Support** — added token limits for glm-5, glm-5-turbo, glm-5.1
- **Compress Role in Frontend** — new `compress` message role rendered as a collapsible card with streaming indicator; i18n keys for compress summary prompt

### Changed
- **Background MCP Startup** — MCP servers now start via `asyncio.create_task` in `lifespan`, no longer blocking app startup; graceful cancellation on shutdown
- **Compression Timing Moved** — context compression check moved from before-LLM to after-LLM response, simplifying DB persistence and agent_switch message handling
- **Token Accumulation** — `AgentContext` now tracks accumulated prompt/completion/cached/reasoning tokens across all iterations; token usage persisted per-iteration
- **Agent Switch Messages Filtered** — `[Agent Switch]` / `[Agent 切换]` messages are filtered out from frontend display when loaded from DB
- **MCP Settings Removed** — SearXNG settings/test tab removed from MCP panel (moved to Settings page)
- **Compress Prompt i18n** — compression system/user prompts moved to i18n en/zh-CN locale files
- Version bumped to 0.9.9.post1

---

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

# Changelog

All notable changes to CrabAgent are documented in this file.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

中文版本：[CHANGELOG.zh-CN.md](CHANGELOG.zh-CN.md)

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

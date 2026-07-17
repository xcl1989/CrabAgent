# Changelog

All notable changes to CrabAgent are documented in this file.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

中文版本：[CHANGELOG.zh-CN.md](CHANGELOG.zh-CN.md)

---

## [0.12.8] — Rich Conversation Visualizations

### Added
- **Rich chat visualizations** — Assistant replies can now render Mermaid diagrams for flowcharts, sequence diagrams, state diagrams, ER diagrams, and architecture relationships. Mermaid loads only when a diagram is present to keep initial chat loading fast.
- **Data charts and KPI cards** — New fenced Markdown blocks render bar, line, area, pie, and scatter charts, plus KPI summary cards. Charts support zooming, copying as PNG, and downloading a high-resolution PNG for easy sharing.
- **Visualization validation tests** — Frontend schema tests cover current chart payloads, legacy saved messages, inferred category fields, invalid data rejection, and KPI parsing.

### Fixed
- **Historical chart compatibility** — Previously saved chart messages using `series: ["field"]` and `xField` are normalized and rendered alongside the current object-based schema.

## [0.12.7] — Ghosting Fix & Image Tool Enhancements

### Fixed
- **Sprite pet ghosting (叠影) in animation** — The cross-correlation alignment in `_align_frames` used `alpha_composite` which blends, not replaces, causing residual semi-transparent pixels to accumulate and create a double-image "ghost" effect. Fixed by properly clearing the canvas before compositing each aligned frame.
- **Pet generation with reference photo for ChatGPT provider** — The `_image_edit` method now detects ChatGPT subscription provider and routes to a dedicated `_chatgpt_image_edit` that calls the Codex responses API with multimodal `input_image` + `image_generation` tool, so the reference image is truly seen by the model.

### Added
- **Enhanced image generation tool** — Added support for reference-image editing (`image_edit` tool), multiple aspect ratios (1:1, 4:3, 3:2, 16:9, 9:16), and automatic style preservation via `ref-preset` mode. The tool can regenerate images with modified prompts while maintaining the original composition.
- **WeChat message processing** — New `wechat_message` tool for reading, replying to, and sending WeChat work messages. Supports message polling, attachment handling, and configurable send intervals.
- **Tool confirmation improvements** — The confirm dialog now shows tool names, execution counts, and allows batch approval. The `tool_confirm` message is persisted so the UI can re-render confirm state after reconnection.

### Changed
- **Pet generation progress bar** — Step labels now show detailed Chinese descriptions for each animation row (idle, running-right, etc.) instead of generic step numbers.
- **Static asset cache** — All frontend builds now include a unique content-hash in filenames to prevent stale cache issues.

---

## [0.12.6] — Desktop Pet Improvements

### Added
- **AI pet generation with reference photo** — When uploading a reference photo, the ChatGPT Codex backend receives the image as multimodal `input_image` content with the `image_generation` tool, so generated spritesheets faithfully reproduce the reference character's identity, colors, and style. OpenAI API providers use `litellm.aimage_edit` for the same effect.
- **ChatGPT rate limit panel overhaul** — The quota display now dynamically formats window sizes (hours/days) and reset times from raw API seconds, adapting automatically to any future window changes (5-hour, 7-day, etc.) without code updates.

### Fixed
- **Pet generation button error `[object Object]`** — The API client was JSON-serializing `FormData` objects, breaking multipart uploads. Fixed: `ApiClient` now passes `FormData` through without serialization and omits `Content-Type` (browser sets multipart boundary). Error responses with non-string `detail` are also stringified properly.
- **Desktop pet click not opening main window** — Pointer-down immediately started the drag timer, causing a tiny window displacement (screen vs client coordinate mismatch) that polluted click/drag detection. Fixed: drag timer only starts after movement exceeds the 4px threshold. Sprite pets now also call `openMain()` on click (previously only SVG pets did).
- **Sprite pet left-right jitter** — AI-generated spritesheet frames had inconsistent character positions across animation frames. Added cross-correlation frame alignment for stationary animation rows (idle, waving, waiting, working, review). Each frame is shifted to minimize pixel difference against frame 0, eliminating residual horizontal drift.
- **Sprite pet image clipping** — CSS `max-width/max-height: 100%` on the canvas caused vertical squish when the container was smaller than the 192×208 frame. Fixed: removed size clamping and enlarged the sprite-mode container to 208px height.
- **Electron pet window too small for sprite frames** — Window height increased from 276px to 320px to fully accommodate 192×208 sprite frames plus the status bubble.

### Changed
- **Pet style selector i18n** — Style labels (Pixel Art, Chibi, Plush, etc.) now support Chinese and English via the i18n system instead of hardcoded English strings.

---

## [0.12.5] — Desktop Pet

### Added
- **Desktop pet (桌宠)** — A floating, always-on-top mascot window for the Electron desktop app. It shows the current agent state (idle, thinking, working, waiting, celebrating, error) via a global SSE stream, can be dragged around the screen, and provides quick access from the tray/menu.
- **SVG mascot character** — A cute, wide-shell crab with animated eyes, claws, and legs. Breathing, blinking, working, and celebrating animations react to agent events in real time.

### Fixed
- **Desktop pet drag crash near screen edges** — Dragging the pet across display boundaries or through screen gaps no longer throws `TypeError: conversion failure` in the main process; coordinates are clamped to the active display work area.
- **Pet state stuck on "thinking" after tasks finished** — The pet now polls `/api/agents/monitor` and resets to idle when no agents are running, preventing stale state when the `agent_end` SSE event is missed.

### Changed
- **Tray & app menus** — Added "Show Desktop Pet" / "Hide Desktop Pet" entries on macOS and Windows.

---

## [0.12.4] — Lazy Image Loading & Multi-Workspace Awareness

### Added
- **Lazy image loading for sessions** — Messages API now strips base64 image data from list responses. Images are fetched on-demand via the new `GET /sessions/{id}/messages/{msg_id}/images` endpoint, reducing initial session load time from seconds to milliseconds for image-heavy conversations.
- **Multi-workspace active session awareness** — The `/agents/monitor` API now returns `workspace` and `title` for each running session. The workspace switcher shows a green badge with the total count of active sessions across all workspaces, and each workspace in the dropdown shows its own active count. Session list items display a pulsing green dot for running sessions.
- **Image placeholder with reserved space** — While images are lazy-loading, a correctly-sized skeleton placeholder is shown to prevent layout shift / scroll jumps.

### Fixed
- **Duplicate `tool_call_id` causes "no corresponding toolcall result" API error** (session 435) — When a model (e.g. kimi-k2) reuses the same `tool_call_id` across turns and the first turn was interrupted, the validation logic would incorrectly match the orphaned tool_calls with a later turn's tool result. Fixed with windowed matching: tool results are only matched within the window between the assistant message and the next user/assistant message.
- **`UnboundLocalError: reasoning_tokens`** (affects v0.11.7 ~ v0.12.3 packaged builds) — The variable was only initialized inside the usage-chunk handler, so when a streaming response (especially ChatGPT subscription with gpt-5.4) didn't include usage data, accessing it later threw `UnboundLocalError`. Fixed by initializing `reasoning_tokens = 0` at the top of the try block.
- **Office `add` command silently inserts at wrong position** — When the AI passed a specific child path (e.g. `/Sheet1/row[19]`) as `element_path` for `add`, OfficeCLI would ignore the index and append to the end. Now the parent path is automatically extracted and `--after` is set to insert at the expected position. Tool descriptions updated to clarify that `add` expects a parent container path.
- **File browser search searches entire filesystem** — When using an absolute-path workspace, the search API received an empty `path` parameter and defaulted to `/`. Fixed by passing the workspace path from the frontend. Search now also matches against file paths (not just file names).

### Changed
- **`message_to_response()` API** — New `strip_images` parameter (default `True`) controls whether base64 image data is stripped from the response. The messages list endpoint always strips; the new images endpoint uses `strip_images=False`.
- **Office tool descriptions** — Enhanced `add` command documentation with explicit warnings that `element_path` is the **parent container path**, with examples for Excel/PPT/Word.

---

## [0.12.3] — Memory Scope & Workspace Isolation

### Added
- **Memory scope system** — AgentMemory now has `scope`, `workspace_path`, and `recall_policy` fields. Memories are classified into four scopes:
  - `global` — cross-workspace knowledge (always injected into system prompt)
  - `workspace` — project-specific knowledge (injected when working in that workspace)
  - `agent` — sub-agent lessons (only recalled via semantic search, never auto-injected)
  - Auto-classification: `team` memories default to `global`, `agent_lesson` to `agent`, `user_preference` to `global`.
- **Workspace-scoped memory prompt injection** — `build_memory_prompt()` now fetches both global (`scope=global, recall_policy=always`) and workspace-scoped (`scope=workspace, recall_policy=always`) team memories, providing contextually relevant knowledge per project.
- **Memory migration script** (`scripts/migrate_memory_scope.py`) — One-time migration that backfills `scope`, `workspace_path`, and `recall_policy` for existing memories using conversation JOIN + curated key lists.

### Changed
- **Memory API** (`/api/memory`) — List endpoint now supports `scope`, `recall_policy`, and `workspace_path` filters directly on the column (previously used a JOIN through conversations). Response includes the three new fields.
- **`memory_save` tool** — Automatically sets `scope` and `recall_policy` based on `memory_type`: `team` → `global/always`, others → `agent/query_only`.
- **Lesson persistence** (`persist_lesson`, `persist_preferences`, `spawn_sub_agent` lessons) — All lesson-saving paths now propagate `workspace_path` and set appropriate `scope`/`recall_policy`.
- **ReflectMiddleware** — Extracts `workspace_path` from `context.metadata` and passes it through to lesson/preference persistence.
- **CLI** — Fixed `build_memory_prompt` calls to pass `workspace_path`; removed duplicate call in `__main__.py`; `workspace_path` now stored in `context.metadata`.
- **Vector search** (`agent_memory_search_vector`, `agent_memory_search`) — Both accept optional `scope` and `workspace_path` filters for finer-grained recall.
- **PyInstaller spec files** — Fixed i18n JSON file collection path to use `_CRABAGENT_ROOT` instead of `SRC`, ensuring correct packaging.

### Fixed
- **`init_db()` migration** — Added ALTER TABLE for `scope`, `workspace_path`, `recall_policy` columns on `agent_memory` table, so upgrades from older versions add the columns automatically.
- **CLI duplicate `build_memory_prompt` call** — The second call without `workspace_path` was overwriting the first result, losing workspace-scoped memories.

### Fixed
- **ChatGPT Rate-Limit Reset Card consumption fails with 400 error** — `_consume_reset_credit` request body was missing the required `redeem_request_id` field, causing OpenAI wham API to reject the request. Added the field to the request payload.
- **CompressMiddleware silently skipped for ChatGPT subscription** — the compression middleware would skip processing when a ChatGPT subscription model was detected, potentially exhausting context window on long sessions.

### Changed
- **Reset Card button now shows confirmation dialog** — clicking "⚡ 立即使用重置" opens a confirmation modal before consuming the reset credit, preventing accidental clicks.
- Upgrade Kimi/Moonshot model list and context window limits.

### Improved
- **SSE reconnection reliability** — pending `user_input` / `confirm` requests are replayed on SSE reconnect, eliminating up to 30s delays.
- **Memory system stability** — delayed imports for `numpy` and `memory_embed` prevent startup crashes in PyInstaller-bundled environments without numpy.
- **Compression quality** — original messages are sent as-is to leverage prompt cache, compressed instructions appended separately; compression prompt character limit enforced to prevent oversized triggers.

---

## [0.11.7] — Image Generation Persistence Fix

### Fixed
- **Generated images disappear after streaming ends** — the root cause was a chain of issues:
  - `_on_image_generated` listened to `TOOL_RESULT` events whose payload was truncated to 2k chars, causing JSON parse failures for larger results. Switched to listen on `MESSAGE_CREATED` which carries the full 20k-char result.
  - Tool messages now include the `name` field so the image handler can identify `image_generate` calls.
  - `/api/files/image` URL with token auth was unreliable for rendering persisted screenshots. Server now inlines base64 `image_data` directly in the message API response, eliminating the secondary authenticated fetch.
  - Frontend merge logic in `agent_end` caused duplicate or missing screenshots when DB already had screenshot records — now properly deduplicates.

### Added
- **`ImageGenerateRender`** — dedicated `ToolResultRender` component for `image_generate` tool results. Extracts image paths from the tool result JSON and renders them inline, providing a fallback display path even if screenshot messages are missing.

### Changed
- `message_to_response` now inlines screenshot images as base64 data URLs in the `image_data` field for direct frontend rendering.
- `Message` type updated with optional `image_data` field.

---

## [0.11.6] — GPT-5.5 Codex + Hotfixes

### Added
- **GPT-5.5 Codex support** — `gpt-5.5` and `gpt-5.4-mini` models are now available for ChatGPT Plus subscribers via Codex API
  - Plus: `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`
  - Pro: `gpt-5.5-pro`, `gpt-5.4-pro`
- **Dynamic litellm model registration** — all `chatgpt/*` subscription models are auto-registered at startup, eliminating "model not mapped" errors

### Fixed
- Outdated ChatGPT subscription model list — verified via live Codex API calls which models actually work on Plus accounts
- `gpt-5.4-pro` removed from default Plus-accessible models (now correctly marked as Pro-only)
- Legacy models (`gpt-5.3-codex` etc.) deprecated in Codex API — kept in list for backward compatibility but noted as possibly unavailable

---

## [0.11.5] — ChatGPT Subscription Support

### Added
- **ChatGPT Plus/Pro Subscription Integration** — use your existing ChatGPT membership to call GPT-5.x Codex models, no API key needed
  - OAuth Device Code Flow: sign in with your ChatGPT account via browser, same as OpenAI Codex CLI
  - Zero API cost — all usage goes through your ChatGPT subscription, not paid API billing
  - 10 models available: `gpt-5.4`, `gpt-5.4-pro`, `gpt-5.3-codex`, `gpt-5.3-codex-spark`, `gpt-5.3-instant`, `gpt-5.3-chat-latest`, `gpt-5.2-codex`, `gpt-5.2`, `gpt-5.1-codex-max`, `gpt-5.1-codex-mini`
  - Token auto-refresh — login once, stays connected for weeks
  - Real-time usage dashboard: 5-hour and 7-day rolling window usage percentages, reset countdowns, credits balance — all from live `x-codex-*` response headers
  - New API endpoints: `POST /api/chatgpt/auth/device-code`, `POST /api/chatgpt/auth/poll`, `GET /api/chatgpt/auth/status`, `POST /api/chatgpt/auth/logout`, `GET /api/chatgpt/account`, `GET /api/chatgpt/models`
  - Provider catalog now includes `chatgpt` type with `auth_type: oauth`
- **Usage Bar Component** — visual progress bars for ChatGPT rate limits with color-coded thresholds (green < 50%, amber 50-80%, red > 80%)

### How to Use
1. Go to **Settings → Providers → Add**
2. Select **"ChatGPT 订阅 (Plus/Pro)"** as the type
3. Click **Add** — no API key required
4. In the provider list, expand the ChatGPT provider and click **"登录 ChatGPT"**
5. A device code appears — open the verification URL in your browser
6. Sign in with your ChatGPT account and enter the code
7. CrabAgent detects login automatically — done!
8. Select a model (e.g., `gpt-5.4`) and start chatting
9. Click **"查看额度"** anytime to see real-time usage and remaining quota

---

## [0.11.2] — Windows Full Compatibility

### Added
- **Windows Desktop App** — `crabagent --build-desktop` now detects the platform and produces a Windows NSIS installer (.exe) on Windows or macOS .dmg
  - New `scripts/build-desktop.ps1` PowerShell build script for Windows
  - electron-builder config: `win` target (NSIS) with desktop/start-menu shortcuts, custom install path, zh_CN + en_US installer UI
  - Electron `main.js` fully cross-platform: `netstat`+`taskkill` port cleanup, `where` path resolution, `explorer` folder open, `windowsHide` console suppression, `taskkill /T /F` process tree kill
- **OfficeCLI Windows Support** — probe paths now include `%LOCALAPPDATA%`, `%PROGRAMFILES%`, `%PROGRAMFILES(X86)%` with `.exe` suffix; install hint shows `winget install HaiYing.OfficeCLI` on Windows

### Fixed
- **bash tool on Windows** — 6 Unix-specific issues fixed:
  - Shell profile commands (`.zprofile`, `.bash_profile`) caused syntax errors in cmd.exe → platform-detected skip on Windows
  - Hardcoded `utf-8` decode caused garbled output (GBK/cp936) → dynamic encoding via `locale.getpreferredencoding()`
  - `nohup ... & echo $!` background mode failed → PowerShell `Start-Process` alternative
  - `ps -p {pid}` process check failed → `tasklist` alternative
  - `start_new_session=True` (POSIX-only) → `creationflags=CREATE_NEW_PROCESS_GROUP|CREATE_NO_WINDOW` on Windows
  - Tool description now says "shell command" instead of "bash command" on Windows
- **TUI crash on Windows** — `logging.FileHandler("/tmp/crabagent.log")` hardcoded Unix path → `tempfile.gettempdir()`
- **OfficeCLI "not installed" on Windows** — `_PROBE_LOCATIONS` were all Unix paths; `documents.py` hardcoded `/usr/local/bin/officecli` as fallback → proper 503 error
- **sandbox.py** — danger path list only had Unix paths; now includes `C:\Windows\System32`, `C:\Program Files`, Windows privilege commands (`runas`, `takeown`, `icacls`, `bcdedit`, `reg delete HKLM`), and physical drive write detection
- **files.py** — `http.server` subprocess popped up a console window on Windows → `CREATE_NO_WINDOW` flag
- **PyInstaller spec** — excluded `msvcrt`, `win32api`, `win32com`, `msilib` which are needed on Windows → conditional exclusion list

---

## [0.11.1]

### Added
- **File Tree Context Menu** — right-click any file or folder in the file browser to manage files
  - **Rename** — inline edit with Enter to confirm, Esc to cancel
  - **Delete** — confirmation dialog with folder/file distinction
  - **New file / New folder** — inline input on directory nodes, auto-expand parent
  - **Download** — browser download with token auth
  - **Copy path** — copy absolute path to clipboard
  - Backend: `DELETE /api/files/manage`, `POST /api/files/rename`, `POST /api/files/create`, `GET /api/files/download`
- **Chat File Upload** — upload any file type (not just images) from the chat input
  - Click 📎 button or drag-and-drop or paste files into the input
  - Office documents (.docx/.xlsx/.pptx), PDFs, text files supported
  - Files stored in `~/.crabagent/uploads/{user_id}/` — not in workspace
  - Uploaded file paths injected into the prompt for Agent to process
  - Pending files shown as cards with icon, name, and size
- **LLM Retry with Live Countdown** — users now see exactly what's happening when API calls fail
  - New `LLM_RETRY` SSE event with phase, attempt number, and countdown
  - Frontend retry card: spinner + message + "X秒后重试（第2/3次）" + progress bar
  - Countdown ticks at 1-second intervals for real-time feedback

### Fixed
- **grep tool** — `{ts,tsx}` brace expansion in `include` parameter silently matched zero files (fnmatch doesn't support `{a,b}`)
- **grep tool** — single-file path search returned "path does not exist" error
- **grep tool** — binary files (databases, images) returned garbled text wasting tokens
- **glob tool** — `Path.glob()` traversed node_modules before filtering (2274 files scanned, 2241 wasted); now uses `os.walk` with pre-pruning (33 files, 132x faster)
- **glob tool** — brace patterns like `*.{ts,tsx}` returned empty results
- **edit tool** — `old_string` not found raised `ValueError` crash instead of friendly error message (count check was after `index()`)
- **read tool** — directory listing hid all dotfiles (.env, .gitignore, etc.) preventing discovery of config files
- **read tool** — binary files returned garbled content instead of a "Binary file" notice
- **glob/grep/read** — inconsistent exclude directory lists across three tools; now aligned (`.crabagent` → `molts` subdirectory)
- **WeChat file download** — `.docx`/`.xlsx`/`.pdf` files from WeChat failed to download because AES decryption validation only checked image magic bytes (JPEG/PNG); now supports all common file types (ZIP/PDF/text/structured data)
- **LLM double-retry** — litellm's built-in retry (`num_retries=3`) stacked with manual loop retry, causing up to 12 actual retry attempts; litellm retry now disabled (`num_retries=0`)
- **LLM retry counter leak** — `_llm_retry_count` never reset on success, so after one failed iteration, subsequent iterations had fewer retry attempts available

### Changed
- **glob/grep/read tools** — all three now accept `context` parameter for workspace-aware path resolution
- **glob tool description** — documents brace expansion support
- **`api.del()`** — now accepts optional body parameter for DELETE requests with payload

---

## [0.11.0]

### Added
- **Office Deep Editing — Excel Table Enhancements** — full spreadsheet interaction from the preview
  - **Merge/Unmerge cells**: drag-select multiple cells in the preview (green rectangle with row background for complete coverage), then click "Merge Cells" toolbar button
  - **Insert/Delete rows & columns**: toolbar buttons for row/column operations
  - **Formula support**: set formulas via toolbar input (`SUM(A1:A10)`), read computed values back in `office_read`
  - **Direct cell editing**: double-click any cell → edit inline → save via `data-path` precise targeting
  - **Batch API**: `POST /api/documents/quick-edit/table-op` for all table operations
  - Agent tool descriptions updated to expose all merge/formula/theme/table properties to LLMs
- **PPT Theme Editor** — modify presentation theme colors and fonts from the preview
  - Backend `POST /api/documents/quick-edit/theme` supports 12 color slots + 2 font slots
  - Frontend color picker with 12 swatches (accent1~6, dk1/lt1/dk2/lt2, hyperlink/followedhyperlink)
  - Font selectors for headingFont and bodyFont with 10 font options

### Fixed
- **Excel batch operations silently failing** — `mgr.batch()` was passing JSON as a positional argument instead of `--commands` flag
- **Template literal regex escaping** — `\/` and `\d` in template literals were consumed by Vite/esbuild during compilation, causing all regex-based `parseCellPath` to fail for non-trivial spreadsheet data
- **Hardcoded sheet name** — merge/formula operations hardcoded `"Sheet1"` instead of using the actual sheet name from `data-path`
- **Cell selection visual feedback** — selection now adds both row-level background (for complete rectangle even on sparse data) and cell-level outlines

---

### Changed
- **Dual-Mode Concept — Chat Mode & Work Mode** — CrabAgent's two working modes are now the central design narrative
  - **Chat Mode 💬** — session list + full-width conversation panel. The default for asking questions, brainstorming, research, and agent delegation
  - **Work Mode 🛠️** — AI chat shrinks to a 350px sidebar, workspace panel takes over the right side with real-time document preview, code editor, prototype builder, or meeting notes
  - **Auto-switch**: when AI creates or opens a file, the interface automatically transitions from Chat Mode to Work Mode; user can switch back with one click
  - **Workspace types**: Document (Office preview + inline edit + timeline), Code (Monaco editor), Prototype (split source/preview), Meeting (structured notes + action items)

### Updated
- **README (EN & ZH)** — fully rewritten to lead with the Chat Mode / Work Mode concept, with ASCII layout diagrams, workspace type table, and real-world workflow examples
- **Platform tagline** — from "Your AI Knowledge Work Platform" to "AI Knowledge Work Platform — Chat when you need answers, Work when you need results"

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

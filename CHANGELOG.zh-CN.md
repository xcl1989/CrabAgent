# 更新日志

CrabAgent 的所有重要变更记录在此文件中。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，并遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

English version: [CHANGELOG.md](CHANGELOG.md)

---

## [0.9.4]

### Added
- Desktop build pipeline: `make desktop` 一条命令构建 PyInstaller 后端 + Electron .dmg
- Memory 页面：浏览/编辑/搜索项目记忆、Agent 经验、用户偏好的独立页面
- LLM 去重：提取时用 LLM 判断是否已有相似内容，避免重复积累
- ChatInput 独立组件：修复消息多时打字卡顿问题

### Changed
- 导航重构：删除 Dashboard，新增 Memory 页签；Agents 增强（统计 + 运行记录）
- 桌面程序打包：新增 `scripts/build-desktop.sh` 一键构建脚本
- 版本号：更新到 0.9.4

### Fixed
- grep 工具：从 glob 改为 os.walk + 剪枝，新增 ignore_dirs/max_depth/文件上限
- 记忆去重：lesson/preference key 从时间戳改为内容 MD5 哈希
- Agent lessons 爆炸：提取时 LLM 去重
- MemoryPage 布局：仅列表滚动，页签和搜索栏固定

---

## [0.9.1]

### 新增
- **子代理完整内容持久化** — 子代理的 tool 调用和结果现在保存到数据库（sub_agent 消息 JSON 的 `detail` 字段），刷新页面后仍可查看完整内容
- **Agents 页面重新设计** — 左右分栏布局：左侧紧凑 agent 列表，右侧详情/编辑面板，学习统计内嵌显示
- **页签状态保持** — 用 state + CSS `hidden` 替代 `react-router-dom` `<Routes>`，切换到 Dashboard/Agents 时 ChatPage 状态不会丢失

### 变更
- **用户消息气泡最大宽度** — 从 720px 缩减到 520px，CJK 文本换行更自然
- **侧边栏底部按钮布局** — 3 个工具按钮（MCP、Tasks、API Keys）改为横向一行排列
- **AgentBar 显示名** — 显示完整 display name 而非仅第一个词
- **移除 `react-router-dom`** 生产依赖（vendor-react 体积从 49KB 降至 0.03KB）

### 修复
- 刷新页面后子代理内容不可见 — `subAgentContents` Map 现在从数据库加载时自动填充
- 数据库加载的子代理消息缺少 `sub_agent_id` — 生成稳定的 `db-sub-${id}` 键
- `scrollbar-none` CSS class 未定义 — 添加了 WebKit 和 Firefox 定义
- 图片 fallback 提示语硬编码中文 — 改为英文
- `--accent-2-border` CSS 变量未定义的引用 — 直接使用 `--border`
- AgentsPage 加载前闪现"No agents" — 添加 loading spinner
- 各页面 header 高度不一致 — 统一为 `h-12`
- `shadow-lg` 原始 Tailwind class — 替换为 `shadow-[var(--shadow-lg)]` 设计 token
- 学习统计 grid 小屏溢出 — 改为 `grid-cols-2 sm:grid-cols-4`

### 移除
- 侧边栏 "Team" 按钮 — 与 Agents 页签重复，仅保留顶部导航入口
- `AgentTeamPanel.tsx` — 逻辑合并到 `AgentsPage.tsx`

---

## [0.9.0]

### 新增
- **Electron 桌面应用** — 原生 macOS 窗口，自动启动 Python 后端、自动登录、支持系统托盘
  - `electron/` 目录，含 `main.js` / `preload.js` / `electron-builder` 打包配置
  - 旧 PySide6 GUI 已移除，换成 Electron + Web UI 方案
  - macOS `.app` + `.dmg` 通过 `npm run build:mac` 构建
  - 螃蟹 emoji（🦀）应用图标，使用 macOS 原生 CoreText 渲染
- **多工作空间支持** — 按工作目录筛选会话
  - `GET /api/sessions?workspace=` 查询参数
  - `GET /api/sessions/workspaces` 端点 — 列出工作空间及会话数量
  - Web UI 新增 `WorkspaceSwitcher` 组件，使用目录选择器替代手动输入路径
  - `list_conversations()` 服务层支持 `workspace` 过滤
- **全局数据库迁移** — 首次启动时自动将 CWD 下的 `crabagent.db` 迁移到 `~/.crabagent/`
  - `init_db()` 中新增 `_migrate_db_to_home()`，检测旧 DB 并复制
  - `db_url` 默认值改为 `~/.crabagent/crabagent.db`

### 变更
- **认证重构** — `hash_password` / `verify_password` 提取到 `core/auth_utils.py` 以便共享
- **移动端适配** — NavBar 小屏仅显示图标、TaskBoard 改为底部抽屉、ChatPanel/InputBar 紧凑布局
- **SSE 重连修复** — `useSSE.ts` 正确处理 `"message_created"` 事件类型

### 修复
- Electron 窗口启动后自动关闭的问题（移除 `titleBarStyle: hiddenInset`，完善生命周期）
- `QFileSystemModel` 导入修正（从 `QtGui` 移到 `QtWidgets`）

### 移除
- PySide6 GUI 模块（`src/crabagent/gui/`）— 由 Electron 替代
- `gui` 可选依赖（`PySide6`、`qasync`、`markdown2`）

---

## [0.8.1]

### 新增
- **长期记忆中间件框架**（`core/agent/middlewares/`）
  - `Middleware` 协议，含 `on_conversation_start` / `before_llm_call` / `on_conversation_end` 三个钩子
  - `MiddlewareChain` 运行器，单个中间件异常自动隔离不影响其它
  - 内置三个中间件：`CompressMiddleware`、`ReflectMiddleware`、`TitleMiddleware`
- **主 Loop 自动反思** — 主 Agent 现在也会在每次对话结束后抽取经验教训和用户偏好（之前仅子 Agent 抽取）
  - 规则引擎 + LLM 反思双轨
  - 新增 `llm_extract_user_preferences()` — Lobehub 风格的行为偏好挖掘（每次会话最多 3 条）
  - 写入 `AgentMemory` 表，`memory_type ∈ {agent_lesson, user_preference}`
- **按 Query 召回记忆** — `build_memory_prompt(user_id, query=...)` 会按关键词搜索与当前消息相关的团队知识 / 历史经验 / 用户偏好，注入 system prompt
- **主 Agent 的经验注入** — 新增 `inject_agent_lessons()` 公共函数，主 Loop 和子 Agent 委派复用同一逻辑
- **会话标题自动生成** — 新会话第一轮交互完成后，通过一次廉价 LLM 调用生成 4-8 字标题；写入 `conversations.title`，标记 `auto_titled=1`（新增列）
- **DOM 感知浏览器工具** — `browser_navigate` / `browser_click` / `browser_type` / `browser_scroll` 现在会给所有可见可交互元素注入 `data-crab-idx` 属性，并返回编号列表（`[1] a "登录"`、`[2] input[email]` 等）
- **`browser_click_index` 工具** — 用 `[N]` 编号点击，无需再盲猜 CSS 选择器；远比传统 `browser_click(selector=...)` 可靠
- **截图嵌入 vision 模型** — 当前模型支持视觉时，浏览器工具结果会附带 base64 `image_url` 块，让 LLM 直接"看见"页面；非视觉模型仍走文字预览 + 路径提示
- **截图历史滚动** — `BrowserManager` 保留最近 N 张（默认 3）截图以控制上下文体积；超过 200KB 的图片自动跳过嵌入
- 新增配置项：`memory_auto_extract`、`memory_auto_recall`、`memory_max_inject`、`browser_strategy`、`browser_screenshot_to_llm`、`browser_screenshot_history`、`browser_screenshot_max_bytes`

### 变更
- 重构 `core/agent/agents.py` — `_classify_task` / `_rule_extract_lesson` / `_llm_reflect_lesson` 迁移到新模块 `core/agent/reflect.py`；子 Agent 委派和主 Loop 中间件共享同一反思逻辑
- `spawn_sub_agent` 中的经验注入改调公共 `inject_agent_lessons()` helper（行为不变）
- `loop.py` 工具结果支持 `str | list[dict]`（多模态）；list 内容持久化时 JSON 序列化，读取时自动还原
- Loop 的 `_build_messages` 路径在 context 挂载中间件时通过 `MiddlewareChain.run_before_llm` 触发压缩，未挂载时回退到直接调用 `compress_context`

### 修复
- 修复 `loop.py` 内联压缩调用未走中间件链的问题
- 修复 `prompt.py` 未传 `query` 给 `build_memory_prompt` 导致首条消息召回失效

---

## [0.8.0]

### 新增
- Web UI 全面重构，全新 CrabAgent 海洋青色设计系统，完整支持明暗双主题（自动检测系统偏好）
- 基于 token 的设计基础，移除所有硬编码十六进制色值
- 可复用 UI 组件库 `frontend/src/components/ui/`：Button、Input、Modal、ConfirmDialog、Toast (sonner)、Tooltip (Radix)、EmptyState、LoadingState、Skeleton、带复制和语法高亮的 CodeBlock
- 新增 `useThemeColors()` hook，recharts SVG 描边颜色自动跟随主题
- 移动端响应式：SessionList 在 `<md` 屏幕下变为滑入式抽屉，ChatPage 工具栏新增汉堡菜单按钮
- AgentsPage 从模态浮层升级为 `/agents` 独立内联页面；ChatPage 仍保留模态模式

### 变更
- Vite `manualChunks` 将 vendor 拆为 4 个 chunk（react / charts / markdown / ui），最大单 chunk 从 1.22 MB 降至 380 kB
- DashboardPage 移除 44 个内联样式和 `AGENT_THEME` 硬编码渐变，改用 `agentColor()` helper + `--agent-*` CSS 变量；Lucide 图标替换 ASCII 字符
- TodoWidget、McpStatusBar、FileBrowser、TaskBoard 全部重构为使用设计 token 和 Lucide 图标

---

## [0.7.4]

### 新增
- 会话内 Agent 切换 — `/agent`（TUI）或 `POST /api/sessions/{id}/agent`（API）切换当前 Agent 身份；工具白名单和模型跟随 Agent 画像，消息自动标记 Agent 信息
- Agent 自创工具 — 通过 `create_tool` / `update_tool` / `delete_tool` 让 Agent 自己编写并注册可复用工具；代码即时验证、存入 `.crabagent/tools/`、跨会话自动加载

### 修复
- TUI 队列与历史竞态：排队输入在渲染未完成时就被发出
- 加载带排队消息的会话时 DB 消息顺序错乱
- 双面板 TUI 中 CJK 字符渲染卡死
- Thinking 文本显示 bug（off-by-one、缓存遗漏、flush 丢失前缀）

---

## [0.7.2]

### 新增
- 双面板 TUI（基于 prompt_toolkit）：可滚动输出区（鼠标滚轮 + PageUp/Down/Home/End）、自适应输入框、实时状态栏。默认模式（`crabagent`），`--old` 回退旧版
- 鼠标文本选择：Shift + 拖动选中输出区文本，Ctrl+C 复制（macOS pbcopy / Linux xclip）
- 交互式浮窗菜单：`/model`、`/sessions`、`/provider` 改为方向键导航的滚动选择弹窗
- 流式 Thinking：`THINKING_DELTA` 事件实时流式渲染，灰色斜体样式
- 斜杠命令补全菜单悬浮显示在输入框上方

---

## [0.7.1]

### 新增
- Pipeline 可视化看板：实时 Pipeline 执行进度、Agent 卡片运行计数、成长趋势图表；历史 Pipeline 自动折叠
- `agent_runs` 表完整记录每次 Agent / Pipeline 执行的元数据（工具调用、耗时、Token、迭代数）；运行历史和 Agent 成长统计 API
- `RunRecorder` — `EventBus` 订阅器，实时为 Pipeline、主代理和子代理执行创建 `agent_runs` 记录

### 修复
- `TEXT_DELTA` / `THINKING_DELTA` 事件不再被 SSE 转发器节流丢弃
- `TEXT_DONE` 处理器使用后端完整文本确保消息完整显示
- `delegate_parallel` 嵌套对象参数不再显示 `[object Object]`

---

## [0.7.0]

### 新增
- 学习品质升级 — LLM 反思改为提取可执行的具体洞察（工具技巧、踩坑经验、领域提示），不再有"completed in X steps"之类的废话
- 失败学习 — Agent 也能从错误中成长
- Web 代理支持 — `CRAB_WEB_PROXY=http://127.0.0.1:7890` 解决防火墙环境下的搜索问题
- 学习看板 — Web UI Agent Team 面板直接查看每个 Agent 的任务统计和历史经验
- 子 Agent 持久化 — 已完成的子 Agent 在 Dashboard 中保留显示 30 分钟

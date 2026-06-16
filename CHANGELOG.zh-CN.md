# 更新日志

CrabAgent 的所有重要变更记录在此文件中。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，并遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

English version: [CHANGELOG.md](CHANGELOG.md)

---

## [0.10.3]

### 修复
- **微信图片接收** — 微信用户发送的图片现在能正确接收、解密并由 Agent 处理
  - **AES key 格式 bug**：iLink 在 `media.aes_key` 中返回的 key 是 base64(hex_string) 双重编码格式，`_normalize_key` 无法解析，fallback 到 MD5 生成错误 key 导致解密出垃圾数据。修复：在 `crypto.py` 中新增 base64-of-hex 解码路径，并在 `download_media()` 中优先使用 `aeskey` 字段（纯 hex 格式）
  - **非 vision 模型的图片处理**：当默认模型无法处理 `image_url` 内容块时，图片会保存到本地文件并附带文字提示，引导 Agent 自行发现并调用可用的图片分析工具（如 MCP vision 工具）。system prompt 已更新，指示 Agent 自动检测图片识别能力
  - **图片尺寸显示**：iLink 不返回图片的 width/height 字段时，`[图片 0x0]` 占位符改为 `[图片]`

### 新增
- **微信会话归档** — 自动滚动归档长微信会话，防止上下文无限增长
  - **日期触发**：会话创建日期不是今天时，在用户回复发送后异步归档
  - **数量兜底**：prior 消息超过 150 条时触发归档
  - **摘要注入**：旧会话由 LLM 压缩为摘要（≤5000 字），旧会话改名为 `(已归档 MM-DD HH:MM)`，新会话创建并注入摘要作为初始上下文
  - **用户无感知**：归档在回复发送完成后异步执行，用户无需等待
  - **优雅降级**：LLM 摘要失败时跳过归档，下次触发时重试

---

## [0.10.2]

### 新增
- **微信渠道（iLink Bot）** — 基于腾讯 iLink Bot API 的完整微信双向通信集成
  - 扫码登录、异步长轮询消息循环（35秒）、AES-128-ECB 媒体加密
  - 收到微信消息自动通过 Agent 处理并回复（支持多轮对话记忆）
  - 可配置微信渠道工作空间；会话标记 `source='wechat'` 实现隔离
  - REST API：`GET /api/wechat/status`、`POST /api/wechat/qrcode`、`PUT /api/wechat/config`、`POST /api/wechat/test`、`GET /api/wechat/conversations`
  - 前端 `WeChatPanel`：绑定状态、工作空间选择、通知开关、会话记录
- **微信通知联动** — 系统通知（定时任务结果、邮件摘要、邮件轮询告警）自动推送微信
  - 按类别开关：任务逾期、定时任务完成、邮件摘要
  - `context_token` 持久化：首次收到消息时自动保存推送目标和 token，服务重启后自动恢复
  - 邮件上下文注入：邮件通知推送到微信时，自动将邮件详情（发件人、主题、正文、草稿）注入微信会话上下文，用户在微信中说"回邮件"时 Agent 有完整上下文
- **设置页 Tab 布局** — 从单页竖滚改为三个 Tab：通用 / 搜索 / 微信渠道
  - 微信面板从 5 个卡片精简为 3 个：账号（绑定+工作空间+自动回复）、通知（开关+推送目标）、会话记录（可折叠）
  - 保存按钮仅在通用/搜索 Tab 显示（微信设置为即时保存）

### 变更
- `_create_notification()` 新增 `category` 参数，用于微信推送路由
- `WeChatNotification.send()` 内存 `_context_store` 为空时回退到持久化的 `notify_target_user` + `cached_context_token`
- `WeChatMessageLoop.start()` 启动时恢复持久化的 context_token 到内存缓存

### 修复
- 微信通知静默失败 "No target user_id and no cached users" — 推送目标现从首次消息自动持久化
- 邮件到微信的上下文断裂：用户在微信说"回邮件"但 Agent 无邮件上下文 — 现自动注入邮件详情到微信会话
- 通用和搜索 Section 重复使用 `Globe` 图标 — 替换为 `SlidersHorizontal` 和 `Search` 图标

## [0.10.1]

### 新增
- **文档 Quick Edit** — 在文档预览上双击文字直接编辑，支持换行分段
  - 后端 `POST /api/documents/quick-edit/text` 端点：纯文本替换（无换行）或按 `\n` 拆分为多个段落（有换行）
  - 前端 iframe 注入编辑脚本：双击→contenteditable→点外部保存/Escape取消
  - 预览 HTML 注入 `white-space: pre-wrap` CSS，让文档内的换行可见
  - 编辑前自动备份到 `~/.crabagent/docs-backup/`

### 修复
- `NameError: name 'json' is not defined` — 补全缺失的 import

## [0.10.0]

### 新增
- **语义记忆搜索** — 记忆召回从 SQL `LIKE` 关键词匹配升级为基于 `sentence-transformers` 的向量相似度搜索
  - 新增 `MemoryEmbedding` 表，为每条记忆存储 384 维 float32 向量（base64 编码）
  - `agent_memory_search_vector()` 使用 余弦相似度 × 0.7 + importance × 0.3 综合排序
  - 未安装 `sentence-transformers` 时自动降级到 LIKE 搜索
  - 新增环境变量 `CRAB_MEMORY_EMBEDDING`：`auto`（默认）/ `on` / `off`
  - 新增可选依赖：`pip install 'crabagent[memory]'`
- **跨 Agent 经验共享** — Agent 现在可以复用其他 Agent 的高质量经验
  - 当自身经验 < 5 条时，自动补充其他 Agent 的经验（importance ≥ 0.7 且相似度 ≥ 0.4）
  - 实现团队间的知识传递（如 coder 可以借鉴 researcher 的搜索策略）
- **记忆质量衰减** — 每周定时任务自动清理过时记忆
  - 每周一 03:00：`access_count=0` 且超过 30 天的记忆 importance 降低 0.1
  - importance < 0.2 且超过 60 天的记忆自动删除
- **数据清理** — 记忆条目从 645 条精简至 530 条（删除重复、低质量、过时项目文档）
- **Bash 流式输出** — bash 工具现在通过 SSE 实时流式输出，不再阻塞等待完成
  - 新增 `BASH_OUTPUT` / `BASH_EXIT` 事件类型，前端终端风格实时显示
  - 超时后自动转后台，返回日志文件路径供后续查看
- **Office 工具修复** — `office_read` 新增 `offset` 参数；`add_element` 支持 `index`/`after`/`before` 定位；`office_query` 输出超 5 万字符时自动截断
- **智能文档处理** — AI Agent 现在可以通过五个内置工具读取、创建、编辑、查询和渲染 Office 文档（`.docx`、`.xlsx`、`.pptx`）：`office_read`、`office_create`、`office_edit`、`office_query`、`office_render`
  - 后端：`OfficeManager` 封装 OfficeCLI 二进制文件执行文档操作
  - 前端：`DocumentPanel` 带拖拽调整手柄、最大化/还原按钮、拖拽遮罩层（防止 iframe 劫持鼠标事件）
  - 前端：`DocumentPreview` 支持文件类型图标、加载/错误状态、HTML 预览
  - SSE 事件实现文档操作实时可视化：`doc_op_start`、`doc_op_delta`、`doc_op_preview`、`doc_op_done`
- **Scrapling 集成增强网页抓取** — `web_scrape` 现在使用 [Scrapling](https://github.com/D4Vinci/Scrapling) 解析器实现高质量结构化 HTML 提取
  - 标题 → Markdown 标题，`<p>` → 段落（含内联链接），`<li>` → 列表，`<tr>` → 表格，`<a>` → `[文本](url)`
  - 新增 `selector` 参数，支持 CSS 选择器精确提取页面元素
  - 自动过滤噪音标签（script、style、nav、footer、侧边栏等）
  - Scrapling 不可用时自动降级到 lxml
- **会话 Agent 持久化** — 加载历史会话时自动恢复上次使用的 Agent 配置
  - 后端：`SessionResponse` 新增 `agent` 字段
  - 前端：自动加载、会话选择、新建会话时均恢复 Agent
- **上下文压缩质量修复** — 压缩摘要不再被截断
  - 提示词从"200-500 字"改为"全面详细，无长度限制，使用 Markdown 格式"
  - `max_tokens` 提高：1024 → 4096
  - 输入截断放宽：工具结果 500→2000 字符，消息 1000→3000 字符

### 变更
- **文档面板布局** — 默认宽度 480→520px，动态最大宽度计算，文档面板打开时聊天内容不再被挤压
- **Univer 死代码清理** — 移除 `UniverEditor.tsx`、`@univerjs/*` 依赖、孤立 i18n 键和"在线编辑"按钮（开源版 Univer 无法导入/编辑已有 Office 文件）
- **文件浏览器** — Git 和 Molts 区块默认折叠
- **DocumentPreview** — 优化加载/错误状态，按文件类型显示图标
- **记忆搜索** — `build_memory_prompt()`、`inject_agent_lessons()` 和 `memory_recall` 工具改用向量搜索，自动降级到 LIKE
- **Team 记忆类型修复** — 修复 `team` 类型记忆从未被注入的问题（原来错误查询 `team_knowledge`）

### 修复
- 文档面板拖拽：iframe 劫持鼠标事件导致拖拽粘死 — 使用透明遮罩层修复
- 最大化按钮：最大化后无法还原 — 修复父容器定位
- 文档面板最大化时聊天内容被挤压 — 动态 maxWidth 计算
- `office_read` 始终从第 1 段返回 — 新增 `offset` 参数
- Bash 工具硬编码 8 秒超时截断正常命令 — 改为流式输出 + 自动转后台

---

## [0.9.9.post1]

### 新增
- **Token 用量追踪** — 新增 `TokenUsage` 数据库模型、聚合查询 API（`/api/token-usage/*`）、前端 `UsagePage` 用量页面，支持每日/小时趋势图、按 Agent/模型分布、缓存命中率统计
- **上下文压缩流式展示** — 压缩摘要现通过 SSE 逐 token 流式传输（`compress_start` / `compress_delta` 事件），前端实时渲染内联卡片
- **MCP 服务器编辑** — MCP 面板支持编辑已有服务器（名称、传输方式、命令、参数、环境变量、请求头），点击铅笔图标进入编辑模式
- **GLM-5 模型支持** — 新增 glm-5、glm-5-turbo、glm-5.1 的 token 限制配置
- **前端压缩消息角色** — 新增 `compress` 消息角色，在对话中渲染为可折叠卡片，带流式动画指示器；压缩提示词移至 i18n 多语言文件

### 变更
- **MCP 后台启动** — MCP 服务器通过 `asyncio.create_task` 在 `lifespan` 中后台启动，不再阻塞应用启动；关闭时优雅取消
- **压缩时机调整** — 上下文压缩从 LLM 调用前移至 LLM 返回后，简化数据库持久化和 agent_switch 消息处理
- **Token 累积统计** — `AgentContext` 新增跨迭代的 prompt/completion/cached/reasoning tokens 累计统计；每次迭代的 token 用量持久化到数据库
- **Agent 切换消息过滤** — 从数据库加载消息时，`[Agent Switch]` / `[Agent 切换]` 消息自动过滤，不在前端显示
- **MCP 设置页签移除** — 从 MCP 面板移除 SearXNG 设置/测试页签（已移至设置页面）
- 版本号更新到 0.9.9.post1

---

---

## [0.9.6]

### 新增
- **i18n 多语言支持** — 英文 (English) + 中文，支持按会话切换语言
- 语言偏好跨会话持久保存
- 语言环境不匹配检测及重建提示

### 修复
- 语言切换现在正确更新 `User.locale` 和 `AppSetting`
- 语言切换失败时添加 console.error 日志

---

## [0.9.5]

### 新增
- **pip 可安装的桌面构建** — 从 pip 安装后执行 `crabagent --build-desktop`
- Electron 源文件包含在 wheel 中

### 变更
- README 更新，增加 `--build-desktop` 用法说明

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

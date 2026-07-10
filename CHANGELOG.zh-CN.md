# 更新日志

CrabAgent 的所有重要变更记录在此文件中。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，并遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

English version: [CHANGELOG.md](CHANGELOG.md)

---

## [0.12.5] — 桌面宠物

### 新增
- **桌面宠物（Desktop Pet）** — Electron 桌面版新增一个悬浮、置顶的吉祥物窗口。它通过全局 SSE 流实时展示当前 Agent 状态（空闲、思考中、工作中、等待确认、任务完成、报错），支持拖拽移动，并可通过托盘/菜单快速显示或隐藏。
- **SVG 吉祥物形象** — Q 版宽壳小螃蟹，眼睛、蟹钳、腿部独立分层，带有呼吸、眨眼、工作、庆祝等状态动画。

### 修复
- **桌宠拖至屏幕边缘崩溃** — 拖拽桌宠跨越显示器边界或屏幕间隙时，不再因坐标转换失败导致主进程 `TypeError`；坐标已被限制在当前显示器工作区内。
- **任务结束后仍显示“正在思考”** — 桌宠现在会轮询 `/api/agents/monitor`，当没有运行中 Agent 时自动回到空闲状态，避免 `agent_end` SSE 事件丢失造成状态滞留。

### 变更
- **托盘与应用菜单** — macOS 和 Windows 菜单中新增“显示桌宠”/“隐藏桌宠”入口。

---

## [0.12.4] — 图片懒加载 & 多工作空间感知

### 新增
- **会话图片懒加载** — 消息列表 API 现在会剥离 base64 图片数据，通过新增的 `GET /sessions/{id}/messages/{msg_id}/images` 端点按需加载。图片密集的会话初始加载时间从数秒降至毫秒级。
- **多工作空间活跃会话感知** — `/agents/monitor` API 现在返回每个运行中会话的 `workspace` 和 `title`。工作空间切换器显示绿色徽章标识所有空间的活跃会话总数，下拉列表中每个工作空间显示各自的活跃数。会话列表中正在运行的会话显示绿色脉冲指示点。
- **图片占位符预留空间** — 图片懒加载期间显示与最终图片尺寸一致的骨架占位符，避免布局抖动和滚动跳跃。

### 修复
- **重复 `tool_call_id` 导致"没有对应的 toolcall 结果"API 报错**（会话 435）— 当模型（如 kimi-k2）跨轮次复用相同 `tool_call_id`，且第一轮被中断时，验证逻辑会错误地将孤立 tool_calls 与后续轮次的 tool 结果匹配。改用窗口匹配：只在 assistant 消息到下一个 user/assistant 消息之间的窗口内查找匹配的 tool 结果。
- **`UnboundLocalError: reasoning_tokens`**（影响 v0.11.7 ~ v0.12.3 打包版）— 该变量仅在 usage chunk 处理器内赋值，当流式响应（特别是 ChatGPT 订阅的 gpt-5.4）不含 usage 数据时，后续访问抛出 `UnboundLocalError`。已在 try 块顶部初始化 `reasoning_tokens = 0`。
- **Office `add` 命令静默插入到错误位置** — 当 AI 将具体子路径（如 `/Sheet1/row[19]`）作为 `element_path` 传给 `add` 时，OfficeCLI 会忽略索引并追加到末尾。现在自动提取父路径并设置 `--after` 在预期位置插入。工具描述已更新，明确说明 `add` 需要父容器路径。
- **文件浏览器搜索整个文件系统** — 使用绝对路径工作空间时，搜索 API 收到空的 `path` 参数并默认搜索 `/`。已从前端传递工作空间路径。搜索现在同时匹配文件名和文件路径。

### 变更
- **`message_to_response()` API** — 新增 `strip_images` 参数（默认 `True`），控制是否从响应中剥离 base64 图片数据。消息列表端点始终剥离；新增的图片端点使用 `strip_images=False`。
- **Office 工具描述** — 增强 `add` 命令文档，明确标注 `element_path` 是**父容器路径**，并提供 Excel/PPT/Word 示例。

---

## [0.12.3] — 记忆分层与工作区隔离

### 新增
- **记忆分层系统** — AgentMemory 新增 `scope`、`workspace_path`、`recall_policy` 三个字段。记忆分为四种作用域：
  - `global` — 跨工作区知识（始终注入系统提示词）
  - `workspace` — 项目专属知识（在该工作区工作时注入）
  - `agent` — 子 Agent 经验教训（仅通过语义搜索召回，不自动注入）
  - 自动分类：`team` 记忆默认 `global`，`agent_lesson` 默认 `agent`，`user_preference` 默认 `global`。
- **工作区级记忆注入** — `build_memory_prompt()` 现在分别获取全局（`scope=global, recall_policy=always`）和工作区级（`scope=workspace, recall_policy=always`）的 team 记忆，为每个项目提供上下文相关的知识。
- **记忆迁移脚本**（`scripts/migrate_memory_scope.py`）— 一次性迁移脚本，通过 conversation JOIN + 精选 key 列表，为已有记忆回填 `scope`、`workspace_path` 和 `recall_policy`。

### 变更
- **记忆 API**（`/api/memory`）— 列表端点支持 `scope`、`recall_policy`、`workspace_path` 过滤，直接查询新列（原先通过 conversation JOIN 实现）。响应包含三个新字段。
- **`memory_save` 工具** — 根据 `memory_type` 自动设置 `scope` 和 `recall_policy`：`team` → `global/always`，其余 → `agent/query_only`。
- **经验教训持久化**（`persist_lesson`、`persist_preferences`、`spawn_sub_agent` 经验提取）— 所有保存路径现在都会传递 `workspace_path` 并设置合适的 `scope`/`recall_policy`。
- **ReflectMiddleware** — 从 `context.metadata` 提取 `workspace_path` 并传递到经验/偏好持久化。
- **CLI** — 修复 `build_memory_prompt` 调用传递 `workspace_path`；移除 `__main__.py` 中的重复调用；`workspace_path` 现存入 `context.metadata`。
- **向量搜索**（`agent_memory_search_vector`、`agent_memory_search`）— 均支持可选的 `scope` 和 `workspace_path` 过滤，实现更精细的召回。
- **PyInstaller spec 文件** — 修复 i18n JSON 文件收集路径，使用 `_CRABAGENT_ROOT` 替代 `SRC`，确保打包正确。

### 修复
- **`init_db()` 迁移** — 为 `agent_memory` 表新增 `scope`、`workspace_path`、`recall_policy` 列的 ALTER TABLE 逻辑，旧版本升级时自动添加列。
- **CLI 重复调用 `build_memory_prompt`** — 第二次调用缺少 `workspace_path`，覆盖了第一次结果，导致工作区记忆丢失。

### 修复
- **ChatGPT 速率限制重置卡消费失败（400 错误）** — `_consume_reset_credit` 请求体缺少 `redeem_request_id` 字段，导致 OpenAI wham API 拒绝请求。已补上该字段。
- **CompressMiddleware 对 ChatGPT 订阅模型静默跳过** — 压缩中间件检测到 ChatGPT 订阅模型时会跳过处理，可能导致长会话耗尽上下文窗口。

### 变更
- **重置卡按钮增加确认弹窗** — 点击"⚡ 立即使用重置"后会弹出确认对话框，防止误触消耗。
- 更新 Kimi/Moonshot 模型列表和上下文窗口限制。

### 改进
- **SSE 重连可靠性** — 挂起的 `user_input` / `confirm` 请求在 SSE 重连时重新发送，消除最长 30s 的延迟。
- **记忆系统稳定性** — `numpy` 和 `memory_embed` 延迟导入，防止无 numpy 环境下 PyInstaller 打包版启动崩溃。
- **压缩质量** — 原样发送消息以利用 prompt cache，压缩指令单独追加；限制压缩 prompt 字符量防止触发失败。

---

## [0.11.7] — 图片生成持久化修复

### 修复
- **生成的图片在流式输出结束后消失** — 根因是一连串问题：
  - `_on_image_generated` 监听 `TOOL_RESULT` 事件，其 payload 被截断到 2k 字符，导致较大 JSON 解析失败。改为监听 `MESSAGE_CREATED`，携带完整的 20k 字符结果。
  - Tool 消息现在包含 `name` 字段，图片处理器可以识别 `image_generate` 调用。
  - 前端用 `/api/files/image` + token 认证 URL 加载持久化截图时不可靠。服务端现在直接在消息 API 响应中内联 base64 `image_data`，消除二次认证请求。
  - `agent_end` 时前端合并逻辑在 DB 已有截图消息时导致重复或丢失——现已正确去重。

### 新增
- **`ImageGenerateRender`** — `image_generate` 工具的专用渲染组件。从工具结果 JSON 中提取图片路径并内联渲染，即使截图消息丢失也能显示。

### 变更
- `message_to_response` 现在将截图图片以 base64 data URL 内联到 `image_data` 字段中，前端可直接渲染。
- `Message` 类型新增可选 `image_data` 字段。

---

## [0.11.6] — GPT-5.5 Codex 支持 + 修复

### 新增
- **GPT-5.5 Codex 支持** — `gpt-5.5` 和 `gpt-5.4-mini` 模型现已在 ChatGPT Plus Codex API 中可用
  - Plus 用户可用：`gpt-5.5`、`gpt-5.4`、`gpt-5.4-mini`
  - Pro 用户额外可用：`gpt-5.5-pro`、`gpt-5.4-pro`
- **动态 litellm 模型注册** — 所有 `chatgpt/*` 订阅模型在启动时自动注册，消除 "model not mapped" 错误

### 修复
- 更新过时的 ChatGPT 订阅模型列表 — 通过实测 Codex API 验证了 Plus 账号实际可用的模型
- `gpt-5.4-pro` 不再列为 Plus 可用（已正确标记为 Pro-only）
- 旧版模型（`gpt-5.3-codex` 等）已在 Codex API 中弃用 — 保留在列表中但注明可能不可用

---

## [0.11.5] — ChatGPT 订阅支持

### 新增
- **ChatGPT Plus/Pro 订阅集成** — 用你现有的 ChatGPT 会员调用 GPT-5.x Codex 模型，无需 API Key
  - OAuth Device Code 认证：用 ChatGPT 账号在浏览器登录，和 OpenAI Codex CLI 完全相同的官方认证流程
  - 零 API 费用 — 所有用量走 ChatGPT 订阅额度，不走 API 计费
  - 支持 10 个模型：`gpt-5.4`、`gpt-5.4-pro`、`gpt-5.3-codex`、`gpt-5.3-codex-spark`、`gpt-5.3-instant`、`gpt-5.3-chat-latest`、`gpt-5.2-codex`、`gpt-5.2`、`gpt-5.1-codex-max`、`gpt-5.1-codex-mini`
  - Token 自动刷新 — 登录一次，长期有效
  - 实时额度面板：5 小时和 7 天滚动窗口用量百分比、重置倒计时、credits 余额 — 全部来自 `x-codex-*` 响应头的实时数据
  - 新增 API 端点：`POST /api/chatgpt/auth/device-code`、`POST /api/chatgpt/auth/poll`、`GET /api/chatgpt/auth/status`、`POST /api/chatgpt/auth/logout`、`GET /api/chatgpt/account`、`GET /api/chatgpt/models`
  - Provider 目录新增 `chatgpt` 类型（`auth_type: oauth`）
- **用量进度条组件** — ChatGPT 速率限制可视化进度条，按阈值变色（绿色 < 50%，黄色 50-80%，红色 > 80%）

### 使用方法
1. 进入 **设置 → Providers → 添加**
2. 类型选择 **"ChatGPT 订阅 (Plus/Pro)"**
3. 点击 **添加** — 无需 API Key
4. 在 Provider 列表中展开 ChatGPT，点击 **"登录 ChatGPT"**
5. 页面显示一个授权码 — 在浏览器中打开验证链接
6. 用你的 ChatGPT 账号登录并输入授权码
7. CrabAgent 自动检测登录成功 — 完成！
8. 选择模型（如 `gpt-5.4`）即可开始使用
9. 随时点击 **"查看额度"** 查看实时用量和剩余配额

---

## [0.11.2] — Windows 全面兼容

### 新增
- **Windows 桌面应用** — `crabagent --build-desktop` 自动检测平台，Windows 上生成 NSIS 安装器（.exe），macOS 上生成 .dmg
  - 新增 `scripts/build-desktop.ps1` PowerShell 构建脚本
  - electron-builder 配置：NSIS 目标，支持桌面/开始菜单快捷方式、自定义安装路径、中英文安装界面
  - Electron `main.js` 全面跨平台：`netstat`+`taskkill` 端口清理、`where` 路径解析、`explorer` 打开目录、`windowsHide` 隐藏控制台、`taskkill /T /F` 进程树终止
- **OfficeCLI Windows 支持** — 探测路径新增 `%LOCALAPPDATA%`、`%PROGRAMFILES%`、`%PROGRAMFILES(X86)%`（含 `.exe` 后缀）；Windows 安装提示 `winget install HaiYing.OfficeCLI`

### 修复
- **bash 工具在 Windows 上** — 修复 6 个 Unix 专用问题：
  - shell profile 命令（`.zprofile`、`.bash_profile`）在 cmd.exe 中语法错误 → Windows 上跳过
  - 硬编码 `utf-8` 解码导致中文乱码（GBK/cp936）→ 动态检测 `locale.getpreferredencoding()`
  - `nohup ... & echo $!` 后台模式失败 → 改用 PowerShell `Start-Process`
  - `ps -p {pid}` 进程检查失败 → 改用 `tasklist`
  - `start_new_session=True`（仅 POSIX）→ Windows 上用 `creationflags=CREATE_NEW_PROCESS_GROUP|CREATE_NO_WINDOW`
  - 工具描述在 Windows 上改为"shell command"而非"bash command"
- **TUI 在 Windows 上崩溃** — `logging.FileHandler("/tmp/crabagent.log")` 硬编码 Unix 路径 → 改用 `tempfile.gettempdir()`
- **OfficeCLI 在 Windows 上提示"未安装"** — 探测路径全为 Unix；`documents.py` fallback 硬编码 `/usr/local/bin/officecli` → 改为正确的 503 错误
- **sandbox.py** — 危险路径列表仅有 Unix 路径；现已包含 `C:\Windows\System32`、`C:\Program Files`，Windows 特权命令（`runas`、`takeown`、`icacls`、`bcdedit`、`reg delete HKLM`），以及物理设备写入检测
- **files.py** — `http.server` 子进程在 Windows 上弹出控制台窗口 → 添加 `CREATE_NO_WINDOW` 标志
- **PyInstaller spec** — 排除列表中的 `msvcrt`、`win32api`、`win32com`、`msilib` 在 Windows 上是必需的 → 改为条件排除

---

## [0.11.1]

### 新增
- **文件树右键菜单** — 在文件浏览器中右键任意文件/文件夹即可管理
  - **重命名** — 内联编辑，Enter 确认，Esc 取消
  - **删除** — 确认弹窗，区分文件/文件夹
  - **新建文件/文件夹** — 目录节点上内联输入，自动展开父目录
  - **下载** — 浏览器下载（token 认证）
  - **复制路径** — 复制绝对路径到剪贴板
  - 后端新增：`DELETE /api/files/manage`、`POST /api/files/rename`、`POST /api/files/create`、`GET /api/files/download`
- **聊天文件上传** — 输入框支持上传任意文件类型（不再限于图片）
  - 点击 📎 按钮、拖拽或粘贴文件到输入框
  - 支持 Office 文档（.docx/.xlsx/.pptx）、PDF、文本文件等
  - 文件存储在 `~/.crabagent/uploads/{user_id}/`，不污染工作目录
  - 上传后文件路径自动注入 prompt，Agent 可直接读取处理
  - 待发送文件以卡片形式展示（图标 + 文件名 + 大小）
- **LLM 重试实时倒计时** — API 调用失败时用户能看到完整的重试过程
  - 新增 `LLM_RETRY` SSE 事件，包含阶段、重试次数、倒计时秒数
  - 前端重试卡片：旋转图标 + 错误信息 + "X秒后重试（第2/3次）" + 进度条
  - 每秒更新倒计时，用户全程感知

### 修复
- **grep 工具** — `{ts,tsx}` 花括号扩展静默匹配零个文件（fnmatch 不支持 `{a,b}` 语法）
- **grep 工具** — 传文件路径搜索报"路径不存在"错误
- **grep 工具** — 二进制文件（数据库、图片）返回乱码浪费 token
- **glob 工具** — `Path.glob()` 先遍历 node_modules 再过滤（扫了 2274 个文件，2241 个浪费）；改用 `os.walk` 预剪枝（33 个文件，提速 132 倍）
- **glob 工具** — `*.{ts,tsx}` 花括号模式返回空结果
- **edit 工具** — `old_string` 不存在时 `ValueError` 崩溃，而非友好错误提示（count 检查在 `index()` 之后）
- **read 工具** — 目录列表隐藏所有 dotfiles（.env、.gitignore 等），无法发现配置文件
- **read 工具** — 二进制文件返回乱码而非"Binary file"提示
- **glob/grep/read** — 三个工具的排除目录列表不一致；已统一（`.crabagent` → 只排除 `molts` 子目录）
- **微信文件下载** — `.docx`/`.xlsx`/`.pdf` 文件下载失败，因为 AES 解密验证只检查图片 magic bytes（JPEG/PNG）；现支持所有常见文件类型（ZIP/PDF/文本/结构化数据）
- **LLM 双重重试** — litellm 内置重试（`num_retries=3`）与手动循环重试叠加，实际重试高达 12 次；现已关闭 litellm 内置重试（`num_retries=0`）
- **LLM 重试计数泄漏** — `_llm_retry_count` 成功后不重置，导致后续迭代可用重试次数递减

### 变更
- **glob/grep/read 工具** — 三个工具均新增 `context` 参数，支持 workspace 感知的路径解析
- **`api.del()`** — 支持可选 body 参数用于带请求体的 DELETE 请求

---

## [0.11.0]

### 新增
- **Office 深度编辑 — Excel 表格增强** — 从预览中直接操作电子表格
  - **合并/取消合并单元格**：在预览中拖拽多选（绿色矩形+行背景全覆盖），点击工具栏"合并单元格"按钮
  - **插入/删除行列**：工具栏按钮直接操作
  - **公式支持**：工具栏输入框设置公式（如 `SUM(A1:A10)`），`office_read` 自动读取计算结果
  - **直接单元格编辑**：双击任意单元格 → 内联编辑 → 通过 `data-path` 精确保存
  - **批量 API**：`POST /api/documents/quick-edit/table-op` 支持所有表格操作
  - Agent 工具描述全面更新，向 LLM 暴露所有公式/合并/主题/表格属性
- **PPT 主题编辑器** — 从预览中修改演示文稿主题配色和字体
  - 后端 `POST /api/documents/quick-edit/theme` 支持 12 色配色 + 2 字体
  - 前端 12 色选色器（accent1~6、dk1/lt1/dk2/lt2、超链接色）
  - 标题字体和正文字体选择器，10 种字体可选

### 修复
- **Excel 批量操作静默失败** — `mgr.batch()` 将 JSON 作为位置参数传递，未使用 `--commands` 标志
- **模板字面量正则转义** — `\/` 和 `\d` 在模板字面量中被 Vite/esbuild 编译时消耗，导致所有基于正则的 `parseCellPath` 对非平凡表格数据失效
- **硬编码 sheet 名称** — 合并/公式操作硬编码 `"Sheet1"`，未使用 `data-path` 中的实际 sheet 名
- **单元格选择视觉反馈** — 现在同时使用行级背景（覆盖稀疏数据的完整矩形）和单元格级边框

---

### 变更
- **双模式概念 — 对话模式 & 工作模式** — CrabAgent 的两种工作模式正式成为产品核心叙事
  - **对话模式 💬** — 会话列表 + 全宽对话面板。默认模式，适合提问、头脑风暴、调研和 Agent 委派
  - **工作模式 🛠️** — AI 对话缩小为 350px 侧边栏，工作区占据右侧，实时显示文档预览、代码编辑器、原型构建器或会议记录
  - **自动切换**：AI 创建或打开文件时，界面自动从对话模式切换到工作模式；用户可一键切回
  - **工作区类型**：文档（Office 预览 + 内联编辑 + 时间线）、代码（Monaco 编辑器）、原型（源码/预览分屏）、会议（结构化记录 + 待办提取）

### 更新
- **README（中英双语）** — 全面重写，以对话模式 / 工作模式为主线，含 ASCII 布局图、工作区类型表和实战示例
- **平台标语** — 从"你的 AI 知识工作平台"升级为"AI 知识工作平台 — 需要答案时对话，需要成果时工作"

---

## [0.10.4]

### 新增
- **日历日视图 — 事件分层显示** — 时间段事件（有结束时间）和时间点提醒（任务截止/无结束时间）现在在视觉上明确区分
  - **块事件**（会议、有时段的任务）：保持原有彩色块状在时间轴上显示
  - **针事件**（提醒、截止）：在时间轴右侧以浮动红色标签显示，精确定位在触发时间点（`translateY(-50%)` 垂直居中）
  - **自适应布局**：存在提醒事件时，块事件自动从右侧收缩 150px，避免重叠
  - **块最小高度**：从 24px 提升到 36px，短事件可读性更好
  - 纯前端改动，仅在 `DayView` 组件中实现，后端零变动

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

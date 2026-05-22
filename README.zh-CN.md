# 🦀 CrabAgent

> 本地 AI Agent 平台 — CLI + Web 双模，浏览器自动化、多模态（图片）支持、MCP 客户端、网页搜索、文件操作、自定义插件等

CrabAgent 是一个 AI Agent 平台，可以从任意项目目录启动。支持终端（CLI）和浏览器（Web UI）两种模式，能够完整访问本地文件、运行工具和插件。

---

## 功能一览

| 功能 | 说明 |
|------|------|
| **双模操作** | CLI 终端 + Web 浏览器，同一套数据 |
| **浏览器自动化** | Playwright 驱动的无头浏览器：导航、点击、输入、截图、提取、滚动 |
| **多模态（图片）** | 支持粘贴、上传、拖拽发送图片；自动检测视觉模型兼容性 |
| **MCP 客户端** | 连接外部 MCP 服务器（stdio + HTTP），持久连接，UI 管理 |
| **网页搜索 & 抓取** | 内置 `web_search`（DuckDuckGo 零配置 + SearXNG 可选）和 `web_scrape` 工具 |
| **文件操作** | 读、写、编辑、搜索、bash 执行 |
| **快照回滚 🦀** | 修改文件前自动拍照，随时回滚 |
| **待办列表** | Agent 管理任务，前端浮窗实时同步 |
| **Agent 提问** | Agent 可以主动问你问题（支持选项选择） |
| **插件系统** | `.crabagent/tools/*.py`，写个函数就是工具 |
| **多 Provider** | 支持 OpenAI、DeepSeek、Anthropic、Google Gemini 等 LiteLLM 兼容 Provider |
| **对话分支** | 从任意消息创建分支，探索不同方向 |
| **技能系统** | SKILL.md 定义领域指令 |
| **上下文压缩** | 长对话自动摘要 |
| **隐私安全** | 数据全在本地，API key 加密存储 |

---

## 快速开始

```bash
# 安装
pip install 'crabagent[serve]'

# 初始化
crabagent init

# CLI — 交互模式
crabagent

# CLI — 单次查询
crabagent "帮我整理这个目录"

# Web UI
crabagent --serve
# → http://localhost:5210
# 默认登录：admin / xcl1989

# Docker
docker compose up -d
```

---

## 安装方式

### pip 安装

```bash
pip install 'crabagent[serve]'
```

可选扩展：
- `pip install 'crabagent[serve]'` — Web UI 依赖
- `pip install 'crabagent[browser]'` — 浏览器自动化（Playwright）
- `pip install 'crabagent[dev]'` — 开发依赖（测试、lint）

安装浏览器自动化后，还需安装 Chromium：
```bash
playwright install chromium
```

### 源码安装

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

## CLI 使用

```bash
# 交互模式
crabagent

# 单次查询
crabagent "列出当前目录的所有文件"

# 指定 provider 和模型
crabagent -p deepseek -m deepseek-chat "写一个 Python 脚本"

# 恢复历史会话
crabagent -s <session_id>

# 列出可用模型
crabagent models

# 管理 provider
crabagent provider list
crabagent provider add

# 查看技能
crabagent skill list
```

### 斜杠命令

| 命令 | 说明 |
|------|------|
| `/exit`, `/quit` | 退出 |
| `/help` | 帮助 |
| `/clear` | 清空对话上下文 |
| `/history` | 显示消息数和 Token 估算 |
| `/model [name]` | 切换模型 |
| `/models` | 列出可用模型 |
| `/provider [cmd]` | 管理 provider |
| `/sessions` | 列出最近会话 |
| `/session [id]` | 加载历史会话 |
| `/new` | 新会话 |
| `/molt [cmd]` | 快照管理（列表/查看/回滚） |
| `/todo [cmd]` | 待办管理 |
| `/skills` | 列出可用技能 |
| `/skill <name>` | 查看技能内容 |
| `/image <path> [msg]` | 发送图片（附带可选消息） |

---

## Web UI

运行 `crabagent --serve`，打开 `http://localhost:5210`。

- **登录** — 默认管理员账号：`admin` / `xcl1989`
- **对话** — 发送消息，流式输出
- **图片支持** — 剪贴板粘贴、点击上传、拖拽放入图片（每条消息最多 5 张，单张最大 5MB）
- **MCP 服务器** — 添加、连接/断开、管理 MCP 服务器
- **设置** — 配置 SearXNG 地址等（MCP 面板 → 设置标签页）
- **网页搜索** — 内置 `web_search` 和 `web_scrape` 工具（默认 DuckDuckGo，可配置 SearXNG）
- **文件浏览器** — 浏览和预览项目文件
- **待办浮窗** — 右下角任务列表，实时同步
- **会话管理** — 创建、切换、删除会话
- **Provider 管理** — 在 UI 中添加配置 provider

---

## 图片 / 多模态支持

CrabAgent 支持 CLI 和 Web UI 中发送图片。

### Web UI
- **粘贴**：Ctrl+V / Cmd+V 从剪贴板粘贴图片
- **上传**：点击附件按钮选择文件
- **拖拽**：直接拖拽图片到聊天区域
- 发送前显示缩略图预览，历史消息中展示图片

### CLI
```bash
# 发送图片并附带消息
/image /path/to/image.png 这张图片里有什么？
```

### 视觉模型检测
CrabAgent 自动检测当前模型是否支持视觉：
- **视觉模型**（Claude 3+、GPT-4o、Gemini 等）：图片以原生多模态格式发送
- **非视觉模型**（DeepSeek、o1-mini 等）：图片保存到临时文件，发送文本占位符（含文件路径），方便 MCP 工具后续处理

### 限制
- 每条消息最多 **5 张**图片
- 单张图片最大 **5MB**
- 支持格式：PNG、JPEG、GIF、WebP

---

## 浏览器自动化

CrabAgent 可以控制无头 Chromium 浏览器与网页交互，基于 [Playwright](https://playwright.dev/python/)。

### 安装

```bash
pip install 'crabagent[browser]'
playwright install chromium
```

> 浏览器工具是可选的 — 未安装 Playwright 时 CrabAgent 其他功能不受影响。

### 可用工具

| 工具 | 需确认 | 说明 |
|------|--------|------|
| `browser_navigate` | 是 | 打开 URL，返回页面标题、内容预览和截图 |
| `browser_click` | 是 | 通过 CSS 选择器或可见文本点击元素 |
| `browser_type` | 是 | 在输入框中输入文本，可选自动提交表单 |
| `browser_screenshot` | 否 | 截取页面截图（可视区域或整页），保存到临时文件 |
| `browser_extract` | 否 | 提取页面或指定元素的文本内容 |
| `browser_scroll` | 否 | 向上或向下滚动页面 |
| `browser_close` | 否 | 关闭浏览器释放资源 |

### 工作原理

- **惰性启动**：首次调用 `browser_navigate` 时才启动浏览器 — 不使用时不占用资源
- **会话级共享**：每个对话共享一个浏览器实例
- **自动清理**：Agent 完成或会话结束时自动关闭浏览器
- **默认无头模式**：设置 `CRAB_BROWSER_HEADLESS=false` 可切换为有头模式（便于调试）
- **截图实时显示**：浏览器截图自动内嵌到对话中，无需打开外部文件
- **图片预览**：点击任意图片（截图或上传）可在全屏遮罩中查看大图
- 截图保存到 `/tmp/crabagent_screenshots/`

### 使用示例

用自然语言让 Agent 操作浏览器：
```
> 打开 https://news.ycombinator.com 并显示前 5 条新闻
> 在 Google 上搜索 "Python async" 并提取搜索结果
> 给当前页面截图
```

---

## MCP（Model Context Protocol）

CrabAgent 作为 **MCP 客户端**，连接外部 MCP 服务器扩展 Agent 能力。

### 支持的传输方式

- **stdio** — 本地子进程（如 `npx -y @mcp/server-filesystem`）
- **HTTP** — 通过 Streamable HTTP 连接远程 MCP 服务器

### 配置

通过 Web UI（MCP 面板）或直接配置数据库。

MCP 工具自动添加前缀 `mcp__{server}__{tool}`，在聊天中以紫色图标区分显示。

### 连接管理

- 持久连接，单例管理 — 避免每次请求启动子进程
- 出错时手动重连 — 在 UI 中点击"重新连接"
- 状态轮询间隔 60 秒

---

## 网页搜索

Agent 内置两个网页工具：

| 工具 | 说明 |
|------|------|
| `web_search` | 搜索网页。配置了 SearXNG 则优先使用，否则使用 DuckDuckGo（无需 API key） |
| `web_scrape` | 抓取任意 URL 并提取可读内容 |

### SearXNG 配置（可选）

如需更好的搜索质量，部署 SearXNG 实例：

```bash
docker run -d --name searxng -p 8888:8080 searxng/searxng
```

在 SearXNG 的 `settings.yml` 中启用 JSON API：
```yaml
search:
  formats:
    - html
    - json
```

在 **设置**（MCP 面板 → 设置标签页）中配置地址，或使用"测试连接"按钮验证。

---

## 自定义插件

在 `.crabagent/tools/` 下放一个 `.py` 文件，Agent 就能调用它。

### 示例：`hello.py`

```python
name = "hello"
description = "向某人打招呼"
parameters = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "要打招呼的名字"},
    },
    "required": ["name"],
}
requires_permission = False  # 设为 True 则每次调用需要确认

def run(name: str) -> str:
    return f"你好，{name}！欢迎使用 CrabAgent。"
```

支持同步函数（`def run`）和异步函数（`async def run`）。

---

## 配置

环境变量 / `.env`：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CRAB_WORKSPACE` | `cwd` | 工作目录 |
| `CRAB_DB_URL` | `sqlite+aiosqlite:///./crabagent.db` | 数据库地址 |
| `CRAB_JWT_SECRET` | 自动生成 | JWT 签名密钥 |
| `CRAB_ENCRYPTION_KEY` | 自动生成 | API key 加密密钥 |
| `CRAB_SERVE_HOST` | `0.0.0.0` | 服务监听地址 |
| `CRAB_SERVE_PORT` | `5210` | 服务端口 |
| `CRAB_AUTO_APPROVE_TOOLS` | `false` | 自动允许工具执行 |
| `CRAB_MAX_ITERATIONS` | `50` | Agent 最大迭代次数 |
| `CRAB_MAX_TOKENS` | `4096` | 最大响应 Token 数 |
| `CRAB_MOLT_KEEP_COUNT` | `20` | 保留的快照数量 |
| `CRAB_BROWSER_HEADLESS` | `true` | 浏览器无头模式（设为 `false` 为有头模式） |

---

## 项目结构

```
CrabAgent/
├── .crabagent/
│   ├── skills/        # 领域技能（SKILL.md）
│   ├── tools/         # 自定义插件工具
│   └── molts/         # 文件快照
├── src/
│   └── crabagent/
│       ├── cli/       # CLI 入口
│       ├── core/      # Agent 循环、工具、事件、数据库
│       │   ├── agent/  # Agent 上下文、循环、工具注册、Token 限制
│       │   └── mcp/    # MCP 客户端管理器
│       └── serve/     # FastAPI 服务 + API 端点
├── frontend/          # React SPA 前端
├── crabagent.db       # SQLite 数据库
├── Dockerfile
├── docker-compose.yml
└── Makefile
```

---

## 开发

```bash
make install
make build      # 构建 Python 包 + 前端
make docker     # 构建 Docker 镜像
```

---

## 协议

本项目采用 **GNU Affero General Public License v3 (AGPLv3)**，非商用可自由使用。

商用（企业内部部署、SaaS、或任何营利活动）需要另外授权，请联系作者。

详见 [LICENSE](LICENSE) 文件。

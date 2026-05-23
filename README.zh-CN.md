# 🦀 CrabAgent

> **AI 团队指挥中心** — 组建一支专属 AI 专家团队，并行委派任务，实时看板监控进度。全部在本地 Web 控制台完成。

CrabAgent 是一个本地优先的 AI Agent 平台。从任意项目目录启动，支持 CLI 终端和 Web 浏览器双模式。数据全在本地，API Key 加密存储，自由选择任意 LLM 提供商。

---

## 为什么选 CrabAgent

| 特性 | 说明 |
|------|------|
| **🤖 AI 团队** | 创建自定义 Agent 画像；并行委派多个 Agent；每个 Agent 可指定独立模型 |
| **📋 实时看板** | 右侧面板实时显示每个 Agent 的状态（运行中/已完成/出错）、进度和工具调用 |
| **@提及委派** | 输入 `@researcher 帮我搜索一下` 自动委派，也可点击工具栏的 Agent 头像 |
| **🔀 并行执行** | 多个 Agent 同时运行 — 调研员搜资料，程序员修 bug，分析师做对比 |
| **📊 结果对比** | 并排查看所有 Agent 的输出，一键导出 Markdown 报告 |
| **⏱ 定时任务** | Agent 按 cron 表达式自主执行，完成后推送通知 |
| **🌐 浏览器自动化** | Playwright 驱动的无头浏览器 — 导航、点击、截图、提取内容 |
| **🖼️ 多模态** | 粘贴/上传/拖拽图片到对话；自动检测模型是否支持视觉 |
| **🔌 MCP 客户端** | 连接外部 MCP 服务器（stdio + HTTP）；工具自动发现并加前缀 |
| **🦀 快照回滚** | 修改文件前自动拍照，随时回滚，不依赖 Git |
| **🔒 隐私安全** | 数据全在本地；API Key 加密存储；零遥测 |

---

## 快速开始

```bash
pip install 'crabagent[serve]'

crabagent init
crabagent --serve          # → http://localhost:5210
                           # 默认登录：admin / xcl1989
```

CLI 单次查询：
```bash
crabagent "帮我整理这个目录"
crabagent -p deepseek -m deepseek-chat "写一个 Python 脚本"
```

---

## AI 团队 — 本地指挥中心

**1. 组建团队** — 侧边栏 → 🤖 Team → + New Agent。定义每个 Agent 的角色、目标、背景故事、指定模型。

**2. 委派任务** — 三种方式：
- 输入框中输入 `@researcher 找一下竞品价格` — 自动识别并发送
- 点击输入框旁的 🤖 按钮 → 选择 Agent → 输入任务 → 发送
- 点击输入框上方的 Agent 头像栏，自动插入 `@提及`

**3. 实时监控** — 右侧任务看板实时显示每个 Agent 的进度：
- 🟣 **运行中** — 紫色脉冲卡片，显示实时步骤计数和计时
- 🟢 **已完成** — 绿色卡片，显示耗时 / Token / 迭代次数
- 🔴 **出错** — 红色卡片，显示错误信息

**4. 查看结果** — 点击任意卡片打开该 Agent 的完整输出，或点击顶部工具栏的 📋 按钮，分栏对比所有结果。一键导出 Markdown。

**5. 并行执行** — 使用 `delegate_parallel` 工具并行运行多个 Agent，或通过 Web 委派弹窗为不同 Agent 分配不同任务。

内置 Agent：

| Agent | 角色 | 适用场景 |
|-------|------|----------|
| 🔍 Researcher | 网络调研员 | 搜索、浏览、数据采集 |
| 📊 Analyst | 数据分析师 | 对比分析、模式识别、报告生成 |
| 💻 Coder | 编程专家 | 编写、审查、调试、重构代码 |
| 📝 Writer | 内容写手 | 写作、编辑、翻译、格式化 |

---

## 定时任务

Agent 按 cron 表达式自主执行。通过对话或侧边栏的 ⏱ Tasks 面板创建：

```
> 每天早上9点打开 Hacker News 把前5条新闻截图给我
> 每30分钟检查这个商品页面，价格低于500就通知我
```

任务完成后，铃铛图标出现通知。点击可跳转到执行结果的对话 — 完整消息历史、截图和工具输出均有保存。

---

## 浏览器自动化

基于 Playwright。安装：`pip install 'crabagent[browser]'` + `playwright install chromium`。

可用工具：`browser_navigate`、`browser_click`、`browser_type`、`browser_screenshot`、`browser_extract`、`browser_scroll`。

```
> 打开 https://news.ycombinator.com 显示前 5 条新闻
> 在 Google 搜索 "Python async" 提取结果
```

浏览器惰性启动（首次调用才启动），每个会话共享一个实例，会话结束自动关闭。截图直接内嵌在对话中。

---

## 图片 / 多模态支持

粘贴（`Ctrl+V`）、上传或拖拽图片到对话。CrabAgent 自动检测当前模型是否支持视觉 — 视觉模型以原生多模态格式发送，非视觉模型发送文件路径占位符。

- 每条消息最多 5 张，单张最大 5MB
- 支持 PNG、JPEG、GIF、WebP
- CLI：`/image /path/to/image.png 这张图片里有什么？`

---

## MCP 客户端

通过 stdio 或 HTTP 连接外部 MCP 服务器。工具自动发现并加前缀 `mcp__{server}__{tool}`，在聊天中有视觉区分。

在侧边栏的 MCP 面板中管理 — 添加、连接、断开、查看工具数量和连接状态。

---

## 网页搜索 & 自定义插件

**网页搜索**：内置 `web_search`（DuckDuckGo，零配置）和 `web_scrape`。可配置 SearXNG 获得更好的搜索质量。

**自定义插件**：在 `.crabagent/tools/` 下放 `.py` 文件即可：

```python
name = "hello"
description = "向某人打招呼"
parameters = {
    "type": "object",
    "properties": {"name": {"type": "string", "description": "名字"}},
    "required": ["name"],
}
requires_permission = False

def run(name: str) -> str:
    return f"你好，{name}！"
```

---

## CLI 命令

| 命令 | 说明 |
|------|------|
| `/exit`, `/quit` | 退出 |
| `/help` | 帮助 |
| `/clear` | 清空对话上下文 |
| `/model [name]` | 切换模型 |
| `/models` | 列出可用模型 |
| `/sessions` | 列出最近会话 |
| `/session [id]` | 加载会话 |
| `/new` | 新会话 |
| `/molt [cmd]` | 快照管理（列表/查看/回滚） |
| `/todo [cmd]` | 待办管理 |
| `/skills` | 列出技能 |
| `/image <path> [msg]` | 发送图片 |

---

## 配置

环境变量或 `.env` 文件：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CRAB_DB_URL` | `sqlite+aiosqlite:///./crabagent.db` | 数据库地址 |
| `CRAB_JWT_SECRET` | 自动生成 | JWT 签名密钥 |
| `CRAB_SERVE_HOST` | `0.0.0.0` | 服务监听地址 |
| `CRAB_SERVE_PORT` | `5210` | 服务端口 |
| `CRAB_MAX_ITERATIONS` | `50` | Agent 最大迭代次数 |
| `CRAB_MAX_TOKENS` | `4096` | 最大响应 Token 数 |
| `CRAB_BROWSER_HEADLESS` | `true` | 浏览器无头模式 |

---

## 安装

```bash
pip install 'crabagent[serve]'          # Web UI + API
pip install 'crabagent[browser]'        # 浏览器自动化
pip install 'crabagent[dev]'            # 测试 + lint
```

Docker：
```bash
docker compose up -d
```

---

## 项目结构

```
CrabAgent/
├── .crabagent/
│   ├── skills/        # 领域技能（SKILL.md）
│   ├── tools/         # 自定义插件工具
│   └── molts/         # 文件快照
├── src/crabagent/
│   ├── cli/           # CLI 入口
│   ├── core/agent/    # Agent 循环、工具、上下文、压缩
│   ├── core/mcp/      # MCP 客户端管理器
│   └── serve/         # FastAPI + API + 调度器
├── frontend/          # React SPA 前端
├── crabagent.db       # SQLite 数据库
└── Makefile
```

---

## 开发

```bash
make install            # 构建前端 + 安装（可编辑模式）
ruff check src/ tests/  # 代码检查
ruff format src/ tests/ # 代码格式化
pytest                   # 运行测试
```

---

## 协议

GNU Affero General Public License v3 (AGPLv3)，非商用可自由使用。

商用（企业内部部署、SaaS、或任何营利活动）需要另外授权，请联系作者。

详见 [LICENSE](LICENSE)。

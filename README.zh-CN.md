# 🦀 CrabAgent

> **AI 团队指挥中心** — 组建能持续学习和进化的 AI 专家团队。委派、并行、流水线，从终端或浏览器实时看板监控进度。

CrabAgent 是一个本地优先的 AI Agent 平台。从任意项目目录启动，支持 CLI/TUI/Web 三种模式。数据全在本地，API Key 加密存储，自由选择任意 LLM 提供商。

---

## 为什么选 CrabAgent

不同于其他 Agent 平台"用完即忘的临时工"，CrabAgent 的 Agent **会学习、会进化**：

| 能力 | 说明 |
|-----|------|
| **🧠 自演化 Agent** | 每次任务完成后自动提取经验教训 — 规则引擎捕捉模式，LLM 反思分析策略。用得越多越聪明。 |
| **🤖 AI 团队** | 自定义 Agent 画像，每个 Agent 可限制工具集、指定独立模型。委派、并行、流水线三种协作模式。 |
| **📊 成长追踪** | 查看每个 Agent 的统计数据：任务数、成功率、经验数、常用类别。`ctrl+space agent_stats` |
| **⏱ 定时 + 实时** | Agent 按 cron 表达式自主执行，也支持 @提及即时委派。所有 Agent 输出实时流式显示。 |
| **🦀 快照回滚** | 修改文件前自动拍照，随时回滚，不依赖 Git。 |
| **🔒 本地优先** | 数据全在本地，API Key 加密存储，零遥测。 |

---

## 快速开始

```bash
pip install 'crabagent[serve]'

crabagent init

# TUI — 双面板交互模式（支持斜杠命令）
crabagent

# TUI (旧版单面板)
crabagent --old

# Web UI
crabagent --serve          # → http://localhost:5210
                           # 默认登录：admin / xcl1989

# CLI 单次查询
crabagent "帮我整理这个目录"
crabagent -p deepseek -m deepseek-chat "写一个 Python 脚本"
```

---

## 自演化 Agent — 核心差异化

Agent 不只是执行任务，**每次执行都会学习成长**。

### 双引擎反思

```
子 Agent 完成任务
    │
    ├─ 规则引擎（即时）
    │   └─ 迭代数过高 (>80%) → "将复杂任务拆分为更小步骤，减少每次迭代使用的工具数"
    │
    └─ LLM 反思（1-3 秒）
        ├─ 提取具体的、可复用的经验：
        │   "DuckDuckGo 搜中文内容结果较少，改用英文关键词可获得更全面的结果"
        │   "对于不稳定的网站，优先使用 web_scrape 直接抓取而不是 web_search"
        ├─ 自动过滤泛化废话回复（"completed in X steps"）
        ├─ 失败也能学习——捕获错误原因及预防方法
        └─ 来源: llm

### 知识持久化

- **团队知识**：技术栈、架构决策、用户偏好 — 每次启动自动注入
- **Agent 经验**：每个 Agent 的行为模式教训 — 执行同类任务前自动加载
- **任务记录**：每次执行完整记录（成功/失败、耗时、Token 数、迭代数）

### 查看成长

```bash
# TUI 中
/agent_stats coder
# → 总任务: 23  成功率: 91%  平均耗时: 14s
# → lessons: 18 (规则: 3, LLM: 15)

# Web UI
# → Agent Team → 学习统计：点击 Agent 名称查看任务统计和所有经验

---

## AI 团队

### 内置 Agent

| Agent | 角色 | 适用场景 |
|-------|------|----------|
| 🔍 Researcher | 网络调研员 | 搜索、浏览、数据采集 |
| 📊 Analyst | 数据分析师 | 对比分析、模式识别、报告生成 |
| 💻 Coder | 编程专家 | 编写、审查、调试、重构代码 |
| 📝 Writer | 内容写手 | 写作、编辑、翻译、格式化 |

### 委派方式

- `@researcher 找一下竞品价格` — @提及自动委派
- 点击工具栏 Agent 头像插入提及
- `/delegate` 命令交互式选择 Agent
- `delegate_parallel` 多 Agent 并行执行
- `run_pipeline` 串联多个 Agent 按依赖执行

### 会话内 Agent 切换

在会话中途切换当前 Agent 身份，不丢失对话历史：

```bash
# TUI
/agent                  # 弹窗选择 5 个 Agent
/agent researcher       # 直接切换
/agent default          # 恢复全部工具

# Web API
POST /api/sessions/{id}/agent  {"agent": "researcher"}
```

- 每个 Agent 有不同工具集（researcher 有 web 工具，coder 有 bash+edit 等）
- System prompt 不变 — **LLM KV 缓存不失效**
- 所有消息自动标记 Agent 信息，历史可追溯
- Model 跟随 Agent 画像自动切换
- 状态栏实时显示当前 Agent：`[deepseek/chat → researcher] Msgs:5 Tok:1234`

### 实时监控

- 🟣 **运行中** — 实时步骤计数和计时
- 🟢 **已完成** — 耗时 / Token / 迭代次数
- 🔴 **出错** — 错误摘要
- Web 端：右侧任务看板，支持分栏结果对比

---

## 更多功能

### 🖼️ 多模态
粘贴/上传/拖拽图片到对话，自动检测模型是否支持视觉。

### 🌐 浏览器自动化
`pip install 'crabagent[browser]'` + `playwright install chromium`

```
> 打开 https://news.ycombinator.com 显示前 5 条新闻
> 在 Google 搜索 "Python async" 提取结果
```

### 🔌 MCP 客户端
连接外部 MCP 服务器（stdio + HTTP），工具自动发现并加前缀。

### 📋 定时任务
```
> 每天早上 9 点打开 Hacker News 把前 5 条新闻截图给我
> 每 30 分钟检查商品页，价格低于 500 就通知我
```

### 🦀 快照回滚
修改文件前自动拍照，`/molt rollback <id>` 即可回滚。

### 🔧 自定义插件

在 `.crabagent/tools/` 下放 `.py` 文件即可：

```python
name = "hello"
description = "向某人打招呼"
parameters = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
requires_permission = False

def run(name: str) -> str:
    return f"你好，{name}！"
```

**或者让 Agent 自己写工具** — AI 可以在会话中帮你编写和注册自定义工具。只需告诉它你需要什么：

```
> 创建一个解析 CSV 文件并提取某列的工具
> 创建一个查询城市天气的工具
```

工具自动存入 `.crabagent/tools/`，即时注册，跨会话持久化。Agent 会通过团队记忆记住自己创建的工具。

---

## CLI / TUI 命令

| 命令 | 说明 |
|------|------|
| `/exit`, `/quit` | 退出 |
| `/help` | 帮助 |
| `/clear` | 清空上下文 |
| `/model [name]` | 切换模型 |
| `/models` | 列出模型 |
| `/provider [cmd]` | 管理提供商 |
| `/sessions` / `/session [id]` | 列出 / 加载会话 |
| `/new` | 新会话 |
| `/agents [cmd]` | Agent 团队管理 |
| `/agent [name]` | 切换当前 Agent |
| `/agent_stats <name>` | Agent 成长统计 |
| `/delegate [@agent] [task]` | 委派任务 |
| `/memory [list\|search\|clear]` | 团队记忆 |
| `/skills` / `/skill <name>` | 列出 / 查看技能 |
| `/molt [cmd]` | 快照管理 |
| `/todo [cmd]` | 待办管理 |
| `/export` | 导出 Markdown |
| `/image <path> [msg]` | 发送图片 |
| `/runs [agent]` | 查看运行记录 |
| `/abort` | 中断执行 |

---

## 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CRAB_DB_URL` | `sqlite+aiosqlite:///./crabagent.db` | 数据库地址 |
| `CRAB_JWT_SECRET` | 自动生成 | JWT 签名密钥 |
| `CRAB_SERVE_HOST` | `0.0.0.0` | 服务监听地址 |
| `CRAB_SERVE_PORT` | `5210` | 服务端口 |
| `CRAB_MAX_ITERATIONS` | `50` | Agent 最大迭代次数 |
| `CRAB_MAX_TOKENS` | `4096` | 最大响应 Token 数 |
| `CRAB_BROWSER_HEADLESS` | `true` | 浏览器无头模式 |
| `CRAB_WEB_PROXY` | （空） | web_search / web_scrape 的 HTTP 代理 |

**v0.7.4 更新亮点**

- 🔄 **会话内 Agent 切换** — 通过 `/agent`（TUI）或 API 在中途切换当前 Agent 身份。不同 Agent 有不同工具集，消息自动标记 Agent 信息用于历史追踪。
- 🛠️ **Agent 自创工具** — Agent 可通过 `create_tool`/`update_tool`/`delete_tool` 自己编写和注册可复用工具。代码即时验证、存入 `.crabagent/tools/`、自动跨会话加载。
- 🐛 **TUI 队列与历史修复** — 修复排队输入在渲染未完成时就发出的竞态条件。修复带排队消息的会话加载时 DB 消息顺序错乱问题。
- 🔤 **TUI CJK 与 Thinking 修复** — 修复双面板 TUI 中 CJK 字符渲染卡死。修复 Thinking 文本显示 bug（off-by-one、缓存遗漏、flush 丢失前缀）。

**v0.7.2 更新亮点**
- 🖥️ **双面板 TUI** — 全新基于 prompt_toolkit 的全屏 TUI：可滚动输出区域（鼠标滚轮 + PageUp/Down/Home/End）、自适应高度的输入框、实时状态栏。默认模式（`crabagent`），`--old` 回退旧版。
- 🖱️ **鼠标文本选择** — 按住 Shift + 鼠标拖动选中输出区域的文本，Ctrl+C 复制（macOS pbcopy / Linux xclip）。
- 💬 **交互式浮窗菜单** — `/model`、`/sessions`、`/provider` 改为方向键导航的滚动选择弹窗，不再打印长列表。
- 🧠 **流式 Thinking** — Agent 推理过程 (`THINKING_DELTA`) 实时流式输出到面板，灰色斜体样式。
- 💡 **补全菜单** — 斜杠命令自动补全以浮窗形式显示在输入框上方。

**v0.7.1 更新亮点**
- 📊 **Pipeline 可视化看板** — 实时展示 Pipeline 执行进度：活跃 Pipeline 步骤进度环、Agent 卡片运行计数、成长趋势图表。历史 Pipeline 自动折叠。
- 🔄 **AgentRun 持久化** — 新增 `agent_runs` 表，完整记录每次 Agent/Pipeline 执行的元数据（工具调用、耗时、Token、迭代数）。提供运行历史和 Agent 成长统计 API。
- 🐛 **流式输出修复** — `TEXT_DELTA` 和 `THINKING_DELTA` 事件不再被 SSE 转发器节流丢弃。`TEXT_DONE` 处理器使用后端完整文本，确保消息显示完整。
- 🛠 **工具参数显示修复** — `delegate_parallel` 嵌套对象参数不再显示 `[object Object]`。
- 📡 **RunRecorder** — EventBus 订阅器，实时为 Pipeline、主代理和子代理执行创建 `agent_runs` 记录。

**v0.7.0 更新亮点**
- 🧠 **学习品质升级** — LLM 反思改为提取**可执行的具体洞察**（工具技巧、踩坑经验、领域提示），不再有"completed in X steps"之类的废话。新增失败学习 — Agent 也能从错误中成长。
- 🌐 **Web 代理支持** — `CRAB_WEB_PROXY=http://127.0.0.1:7890` 解决防火墙环境下的搜索问题。
- 📊 **学习看板** — Web UI Agent Team 面板直接查看每个 Agent 的任务统计和历史经验。
- 📡 **子 Agent 持久化** — 已完成的子 Agent 在 Dashboard 中保留显示 30 分钟。

---

## 安装

```bash
pip install 'crabagent[serve]'          # Web UI + API
pip install 'crabagent[browser]'        # 浏览器自动化
pip install 'crabagent[dev]'            # 测试 + lint
```

```bash
# 开发模式
make install            # 构建前端 + 安装（可编辑模式）
ruff check src/ tests/  # 代码检查
ruff format src/ tests/ # 代码格式化
pytest                   # 运行测试
```

---

## 项目结构

```
CrabAgent/
├── src/crabagent/
│   ├── cli/           # CLI 入口 + TUI
│   ├── core/agent/    # Agent 循环、工具、压缩、agents
│   ├── core/mcp/      # MCP 客户端管理器
│   └── serve/         # FastAPI + API + 调度器
├── frontend/          # React SPA 前端
└── crabagent.db       # SQLite 数据库
```

---

## 协议

GNU Affero General Public License v3 (AGPLv3)，非商用可自由使用。

商用（企业内部部署、SaaS、或任何营利活动）需要另外授权，请联系作者。

详见 [LICENSE](LICENSE)。

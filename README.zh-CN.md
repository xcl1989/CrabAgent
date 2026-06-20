# 🦀 CrabAgent

> **AI 知识工作平台** — 需要答案时对话，需要成果时工作。两种模式，无缝切换。终端、浏览器、桌面，哪里都能用。

CrabAgent 是一个本地优先的 AI 平台，内置**两种工作模式**，随时适应你正在做的事情：

| | 对话模式 💬 | 工作模式 🛠️ |
|---|---|---|
| **布局** | 会话列表 + 对话面板 | AI 侧边栏 + 实时工作区 |
| **专注** | 聊、问、想 | 创建、编辑、构建 |
| **右侧面板** | — | 文档预览 / 代码编辑 / 原型 / 会议记录 |
| **切换** | 工具栏点 🛠️ 图标 | 点 💬 图标，或 AI 打开文件时自动切换 |

不需要提前选择模式。直接开始聊天，当 AI 开始操作文档或代码文件时，工作区自动滑出。随时切回对话模式，回到纯净的对话界面。

```
对话模式                           工作模式
┌──────┬──────────────┐           ┌──┬──────────┬────────────────┐
│      │              │           │  │ AI 对话  │    工作区      │
│ 会话 │    对话      │           │ 💬│ 侧边栏   │  ┌──────────┐  │
│ 列表 │              │           │  │ (350px)  │  │ 文档预览 │  │
│      │              │           │  │          │  │ 代码编辑 │  │
│      │              │           │  │  输入框   │  │ 原型     │  │
│      │              │           │  │          │  │ 会议记录 │  │
└──────┴──────────────┘           │  │          │  └──────────┘  │
                                  └──┴──────────┴────────────────┘
```

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

**[English](README.md)** | **[中文](README.zh-CN.md)**

---

## 💬 对话模式 — 纯粹对话

默认模式。左侧会话列表，右侧全宽对话面板，没有干扰。

**适合场景：**
- 提问，获得 AI 驱动的回答
- 头脑风暴，探索想法
- 通过网页搜索和浏览器自动化进行快速调研
- 委派任务给专业 Agent（研究员、分析师、编程专家、内容写手）
- 多轮对话，带完整项目记忆

```
你: "帮我分析一下这个项目的架构"
AI: [读取文件、分析模式、生成结构化报告]
你: "把分析结果整理成一份 Word 文档"
AI: [创建文档] → 自动切换到工作模式，右侧打开预览
```

---

## 🛠️ 工作模式 — AI + 实时工作区

当 AI 创建或打开文件时，界面自动分屏：AI 对话缩小为左侧 350px 侧边栏，**工作区**占据右侧主区域。AI 的每一步操作都实时可见。

### 工作区类型

| 类型 | 显示内容 | 触发方式 |
|------|---------|---------|
| 📄 **文档** | Office 文档预览（`.docx` / `.xlsx` / `.pptx`），含大纲、时间线、内联编辑 | AI 创建/打开 Office 文件 |
| 💻 **代码** | 基于 Monaco 的代码编辑器，语法高亮 | AI 处理代码文件 |
| 🔬 **原型** | 分屏：左侧源码，右侧实时预览 | AI 构建 HTML/JS 原型 |
| 📝 **会议** | 结构化会议记录面板，自动提取待办事项 | 点击"开始会议" |

### 工作模式特性

- **实时预览**：AI 编辑文档时即时看到变化
- **内联编辑**：在文档预览中双击文字直接修改
- **AI 编辑工具栏**：加粗、斜体、字号、颜色——一键设置样式
- **自然语言编辑**：输入指令如"把标题改成红色"，AI 自动执行
- **文档时间线**：查看 AI 对文档的完整操作历史
- **文件浏览器**：不离开工作模式即可浏览项目文件
- **一键切回对话模式**，工作完成即回到纯净界面

```
工作模式实战：

你: "读取 sales.xlsx 汇总 Q1 数据，做成一份报告"
                          │
  ┌───────────────────────┼───────────────────────────────┐
  │  AI 对话侧边栏        │  工作区（文档预览）            │
  │                       │                               │
  │  AI: 正在读取文件...  │  ┌─────────────────────────┐  │
  │  AI: Q1 总计: 120万   │  │  Q1 销售报告            │  │
  │  AI: 正在创建文档...  │  │  ───────────────        │  │
  │  AI: 完成！✓          │  │  总计: ¥1,200,000       │  │
  │                       │  │  增长率: +23%           │  │
  │  [输入框: 继续...]    │  │  ...                    │  │
  │                       │  └─────────────────────────┘  │
  └───────────────────────┴───────────────────────────────┘
```

---

## 🤖 AI 团队

两种模式都可以使用专业 Agent 团队：

| Agent | 角色 | 适用场景 |
|-------|------|----------|
| 🔍 Researcher | 网络调研员 | 搜索、浏览、数据采集 |
| 📊 Analyst | 数据分析师 | 对比分析、模式识别、报告生成 |
| 💻 Coder | 编程专家 | 编写、审查、调试、重构 |
| 📝 Writer | 内容写手 | 写作、编辑、翻译、格式化 |
| 📋 Plan Creator | 任务规划师 | 将复杂任务拆解为工作流 |

### 协作方式

```
委派      → @researcher "调研一下竞品定价"
并行      → 同时让 3 个 Agent 做不同任务
流水线    → 调研 → 分析 → 写报告（自动传数据）
交接      → 一个 Agent 做完，另一个接着做
```

---

## 📬 邮件智能 — 收件箱变待办清单

CrabAgent 替你盯着收件箱，把邮件自动变成任务：

```
收件："明天下午3点开会讨论新功能"
      │
      ├─ 🧠 LLM 分析：检测到会议 + 截止时间
      ├─ 📝 自动生成回信草稿
      ├─ ✅ 创建任务："参加关于crabagent的会议"（明天下午3点截止）
      └─ 🔗 任务关联邮件原文 — 点击"查看详情"直达对话
```

不需要规则配置，不需要正则匹配。LLM 智能识别。

---

## 💬 微信渠道 — AI 随身携带

扫码绑定微信账号，CrabAgent 就在你的手机里。

```
你（微信）: "看一下26年1月有啥工作"
       │
       ├─ 🤖 Agent 带着完整项目上下文处理
       ├─ 💬 直接在微信里回复
       └─ 🔔 推送通知：任务逾期、定时任务完成、邮件摘要
```

**三种交互模式：**
- **指令执行** — 从微信发指令，Agent 执行后回复
- **主动通知** — 任务截止提醒、定时任务结果、邮件摘要自动推送
- **对话聊天** — 多轮对话，带完整项目记忆

---

## 🔑 ChatGPT 订阅 — 用你的 Plus/Pro 会员

已经在付 ChatGPT Plus 或 Pro 订阅了？直接在 CrabAgent 里用 — **不需要 API Key，不产生额外费用**。

```
设置 → Providers → 添加 → "ChatGPT 订阅 (Plus/Pro)"
       │
       ├─ 🔐 点击"登录 ChatGPT" → 获取授权码
       ├─ 🌐 浏览器打开 auth.openai.com/codex/device
       ├─ ✍️ 用 ChatGPT 账号登录，输入授权码
       ├─ ✅ CrabAgent 自动检测登录成功
       └─ 📊 点击"查看额度" → 实时配额面板：
            ┌──────────────────────────────────┐
            │ 订阅: PLUS     等级: premium       │
            │                                   │
            │ 5小时窗口   ██░░░░░░░  12.3%      │
            │ 7天窗口     █░░░░░░░░   3.1%      │
            │ 重置倒计时: 4.2小时 / 6.2天       │
            └──────────────────────────────────┘
```

**可用模型：** `gpt-5.4`、`gpt-5.3-codex`、`gpt-5.3-instant`、`gpt-5.2-codex` 等 — 全部走你的 ChatGPT 订阅额度。

**原理：** CrabAgent 使用和 OpenAI Codex CLI 完全相同的 OAuth Device Code 官方认证流程。你的 ChatGPT 登录凭证存储在本地并自动刷新。所有 API 调用通过 `chatgpt.com/backend-api/codex` 走订阅额度 — 不消耗付费 API credits。

---

## 🧠 项目记忆 & 自进化 Agent

每次你在项目里工作，CrabAgent 自动从对话中提取经验教训和偏好。下次打开，它已经知道了：

```
=== 项目上下文 ===
上次活跃：06-05 15:30
技术栈：Python / FastAPI / SQLAlchemy
项目经验：N+1 查询用 selectinload 优化；API 文档用 OpenAPI 规范
====================
```

每次任务完成后，Agent 会反思什么有效（什么无效），并把经验永久存下来：

| 层级 | 范围 | 存储内容 |
|------|------|---------|
| **项目记忆** | 每个工作目录 | 近期经验、技术栈、活跃时间线 |
| **用户偏好** | 全局用户 | 沟通风格、工具偏好、被拒绝的模式 |
| **Agent 经验** | 每个 Agent | 技术策略、常见陷阱、有效方法 |

---

## 快速开始

```bash
pip install crabagent
crabagent init

# TUI — 双面板交互模式
crabagent

# Web UI — 对话模式 & 工作模式
crabagent --serve          # → http://localhost:5210
                           #   默认登录：admin / xcl1989

# CLI 单次查询
crabagent "帮我整理这个目录"
```

### 桌面应用 (macOS & Windows)

构建 Electron 壳（需要系统已安装 Python 和 `crabagent`）：

```bash
# 从 git clone 项目一条命令构建：
make desktop                       # macOS → CrabAgent-x.x.x-arm64.dmg

# 或者从 pip 安装后（自动检测平台）：
crabagent --build-desktop          # macOS → .dmg | Windows → .exe 安装器

# Windows (PowerShell)：
.\scripts\build-desktop.ps1        # → CrabAgent-x.x.x-setup.exe
```

---

## 功能特性

### 🛠️ 工作模式
分屏工作区：实时文档预览、代码编辑器、原型构建器、会议记录、Markdown 编辑器。AI 对话侧边栏全程保持交互。

### 📝 Markdown 编辑器
`.md` 文件分屏编辑器——左侧源码，右侧实时渲染预览。双向滚动同步，支持 GFM 表格、代码语法高亮。可在源码 / 分屏 / 预览三种视图间切换。

### 📄 智能文档处理
AI Agent 可以在对话中直接读取、创建、编辑和预览 Office 文档（`.docx`、`.xlsx`、`.pptx`）。

### 🧠 项目记忆
跨会话记住项目上下文。零额外成本。

### 🖼️ 多模态
粘贴/拖拽图片到对话，自动检测模型是否支持视觉。

### 🌐 浏览器自动化
```bash
pip install 'crabagent[browser]'
playwright install chromium
```

### 🔌 MCP 客户端
连接外部 MCP 服务器（stdio + HTTP），工具自动发现并加前缀。

### ⏱ 定时任务
```
> 每天早上 9 点打开 Hacker News，截图前 5 条发给我
> 每 30 分钟检查商品页，价格低于 500 就通知我
```

### 🦀 快照回滚（Molt）
修改文件前自动拍照，随时回滚，不依赖 Git。

### 🔧 自定义工具
在 `.crabagent/tools/` 下放 `.py` 文件即可。或者让 AI 在对话中帮你创建。

### 🌐 多语言支持
用你熟悉的语言。CrabAgent 支持 **英文 (English)** 和 **中文**，随时切换，不丢失上下文。

---

## 安装

```bash
pip install crabagent                    # CLI + Web UI + API（开箱即用）
pip install 'crabagent[browser]'        # 浏览器自动化
pip install 'crabagent[dev]'            # 测试 + lint
```

### 开发模式

```bash
make install            # 构建前端 + 安装（可编辑模式）
ruff check src/ tests/  # 代码检查
ruff format src/ tests/ # 代码格式化
pytest                   # 运行测试
```

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
| `/memory [list|search|clear]` | 团队记忆 |
| `/skills` / `/skill <name>` | 列出 / 查看技能 |
| `/molt [cmd]` | 快照管理 |
| `/todo [cmd]` | 待办管理 |
| `/export` | 导出 Markdown |
| `/image <path>` | 发送图片 |
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

---

## 项目结构

```
CrabAgent/
├── src/crabagent/
│   ├── cli/           # CLI + TUI
│   ├── core/agent/    # Agent 循环、工具、压缩
│   ├── core/mcp/      # MCP 客户端管理器
│   ├── core/          # 数据库、配置、项目记忆
│   └── serve/         # FastAPI + API + 调度器
├── frontend/          # React SPA 前端
├── electron/          # Electron 桌面应用
├── scripts/           # 构建脚本
├── crabagent.spec     # PyInstaller 编译配置
└── crabagent.db       # SQLite 数据库
```

---

## 协议

GNU Affero General Public License v3 (AGPLv3)，非商用可自由使用。
商用（企业内部部署、SaaS、或任何营利活动）需要另外授权，请联系作者。

详见 [LICENSE](LICENSE)。

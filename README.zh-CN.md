# 🦀 CrabAgent

> **你的 AI 知识工作平台** — 不是又一个编码助手。一个能让 AI 记住你的项目、了解你的风格、越用越聪明的平台。终端、浏览器、桌面，哪里都能用。

CrabAgent 是一个本地优先的知识工作平台。你带来项目和 API Key，它带来一队 AI Agent——**记住你做过什么，学会你怎么工作，用得越多越离不开。**

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

**[English](README.md)** | **[中文](README.zh-CN.md)**

---

## 为什么选 CrabAgent

大多数 AI 工具是"临时工"——干完活就忘。CrabAgent 不一样：

| 不一样在哪 | 对你意味着什么 |
|-----------|--------------|
| **🧠 项目记忆** | 它记得你在每个项目里做了什么。下次打开，它知道你上次停在哪。 |
| **📈 越用越懂你** | 用得越多，它越了解你的偏好、你的代码风格、你的决策习惯。 |
| **🤖 AI 团队协作** | 研究、编码、分析、写作——多个专业 Agent 协同工作，你只需说一句。 |
| **🔒 本地优先** | 数据全在本地，API Key 加密存储，无遥测，无厂商锁定。 |

这种差异是**随时间累积**的：

```
第 1 天：  "挺好用的 AI 工具。"
第 1 周：  "它记得我的项目。不错。"
第 1 月：  "我的整个工作流都跑在上面了。回不去了。"
```

---

## 🧠 项目记忆 — 用过的都知道

每次你在项目里工作，CrabAgent 自动从对话中提取教训和偏好。下次打开，它已经知道了：

```
=== 项目上下文 ===
上次活跃：06-05 15:30
技术栈：Python / FastAPI / SQLAlchemy
项目经验：N+1 查询用 selectinload 优化；API 文档用 OpenAPI 规范
====================
```

这不是"临时生成的摘要"。它来自 Agent 已经提取过的经验教训——**零额外 token 开销，不影响 LLM 上下文缓存。**

---

## 📈 自进化 Agent — 核心差异

每次任务都在教会你的 Agent 一些东西。执行完成后，它会反思什么有效（什么无效），并把经验永久存下来。

### 双引擎反思

```
Agent 完成任务
    │
    ├─ 规则引擎（即时）
    │   └─ "迭代次数过高 → 拆分为更小步骤"
    │
    └─ LLM 反思（1-3 秒）
        ├─ 提取可复用的具体经验：
        │   "DuckDuckGo 搜中文结果少，改用英文关键词"
        │   "不稳定的网站优先用 web_scrape 直接抓取"
        ├─ 自动过滤泛化废话
        └─ 失败也能学——记录错误原因和预防方法
```

### 三层记忆

| 层级 | 范围 | 存储内容 |
|------|------|---------|
| **项目记忆** | 每个工作目录 | 近期经验、技术栈、活跃时间线 |
| **用户偏好** | 全局用户 | 沟通风格、工具偏好、被拒绝的模式 |
| **Agent 经验** | 每个 Agent | 技术策略、常见陷阱、有效方法 |

### 查看成长

```bash
# TUI
/agent_stats coder
# → 总任务: 23  成功率: 91%  平均耗时: 14s
# → lessons: 18 (规则: 3, LLM: 15)

# Web UI: Agent Team → 学习统计
```

---

## 🤖 AI 团队

### 内置 Agent

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

### 实时监控

- 🟣 **运行中** — 实时显示步骤、耗时、工具调用
- 🟢 **已完成** — 耗时 / Token / 迭代次数
- 🔴 **出错** — 错误摘要
- Web：右侧任务看板，支持分栏结果对比

---

## 快速开始

```bash
pip install 'crabagent[serve]'

crabagent init

# TUI — 双面板交互模式
crabagent

# Web UI
crabagent --serve          # → http://localhost:5210
                           # 默认登录：admin / xcl1989

# CLI 单次查询
crabagent "帮我整理这个目录"
```

### 桌面应用 (macOS, 开发模式)

构建 Electron 壳（需要系统已安装 Python 和 `crabagent`）：

```bash
make desktop
# → electron/dist-electron/CrabAgent-0.9.4-arm64.dmg
```

或者直接在浏览器中使用：

```bash
crabagent --serve          # → http://localhost:5210
                           # 默认登录：admin / xcl1989
```

---

## 功能特性

### 🧠 项目记忆
跨会话记住项目上下文。零额外成本。

### 🖼️ 多模态
粘贴/拖拽图片到对话，自动检测模型是否支持视觉。

### 🌐 浏览器自动化
```bash
pip install 'crabagent[browser]'
playwright install chromium
```
```
> 打开 https://news.ycombinator.com 显示前 5 条新闻
> 在 Google 搜索 "Python async" 提取结果
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
```
/molt rollback <id>
```

### 🔧 自定义工具
在 `.crabagent/tools/` 下放 `.py` 文件即可。或者让 AI 在对话中帮你创建。

---

## 安装

```bash
pip install 'crabagent[serve]'          # CLI + Web UI + API
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
| `/memory [list\|search\|clear]` | 团队记忆 |
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

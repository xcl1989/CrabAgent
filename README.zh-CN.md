# 🦀 CrabAgent

> 本地 AI 助手 — CLI + Web 双模，文件操作、自定义插件、对话回滚等

CrabAgent 是一个 AI Agent 平台，可以从任意项目目录启动。支持终端（CLI）和浏览器（Web UI）两种模式，能够完整访问本地文件、运行工具和插件。

---

## 截图

```
待补充 — Web UI 和 CLI 截图
```

---

## 功能一览

| 功能 | 说明 |
|------|------|
| **双模操作** | CLI 终端 + Web 浏览器，同一套数据 |
| **文件操作** | 读、写、编辑、搜索、bash 执行 |
| **快照回滚 🦀** | 修改文件前自动拍照，随时回滚 |
| **待办列表** | Agent 管理任务，前端浮窗实时同步 |
| **Agent 提问** | Agent 可以主动问你问题（支持选项选择） |
| **插件系统** | `.crabagent/tools/*.py`，写个函数就是工具 |
| **多 Provider** | 支持 OpenAI、DeepSeek、Anthropic 等 |
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
- `pip install 'crabagent[dev]'` — 开发依赖（测试、lint）

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

---

## Web UI

运行 `crabagent --serve`，打开 `http://localhost:5210`。

- **注册 / 登录** — 创建账号
- **对话** — 发送消息，流式输出
- **文件浏览器** — 浏览和预览项目文件
- **待办浮窗** — 右下角任务列表，实时同步
- **会话管理** — 创建、切换、删除会话
- **Provider 管理** — 在 UI 中添加配置 provider

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

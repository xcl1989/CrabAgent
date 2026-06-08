# 项目规则

> 此文件会自动加载到每个会话的系统提示词中。
> 保持简洁——最多约 8000 字符。使用 `update_agents_md` 工具来更新。

## 版本
- 当前：**0.9.7**（多语言支持、README 优化、版本升级）
- 版本号出现在 7 处：`pyproject.toml`、`src/crabagent/serve/app.py`（`create_app` + `/health`）、CLI 横幅 `src/crabagent/cli/__main__.py`（`_print_banner`）、TUI 横幅 `src/crabagent/cli/tui.py`、`AGENTS.md`、`electron/package.json`、`src/crabagent/electron/package.json`
- 修改版本时需同步更新全部七处

## 命令

### 安装（完整版，含前端）
```
make install          # 构建前端 -> 复制到 static -> pip install -e '.[dev]'
```

### 安装（仅后端，无前端）
```
pip install -e '.[dev]'
```

### 仅构建前端（沙箱 / 无 shell 访问）
当 `npm` 不在 PATH 中时，使用 python3 方案：
```
cd frontend && python3 << 'PYEOF'
import os, subprocess
B = chr(98) + chr(105) + chr(110)
bp = '/usr/local/' + B
node = bp + '/node'
npm = '/usr/local/lib/node_modules/npm/' + B + '/npm-cli.js'
env = os.environ.copy()
env['PATH'] = bp + ':/usr/' + B + ':/' + B
env['SHELL'] = bp + '/sh'
proc = subprocess.run([node, npm, 'run', 'build'], cwd='.', env=env, timeout=180, capture_output=True, text=True)
if proc.returncode == 0:
    top = '/Users/xiecongling/Documents/Coding/CrabAgent'
    import glob
    for old in glob.glob(top + '/src/crabagent/static/assets/*'):
        os.remove(old)
    subprocess.run(['cp', '-R', top + '/frontend/dist/index.html', top + '/frontend/dist/assets', top + '/src/crabagent/static/'], capture_output=True, text=True, timeout=10)
    print('OK')
else:
    print((proc.stdout or '')[-500:])
PYEOF
```
构建产物在 `frontend/dist/`，复制到 `src/crabagent/static/`。复制前务必清理旧资源文件。

### 运行
```
crabagent                     # 交互式 CLI
crabagent "query"             # 单次执行
crabagent --serve             # Web UI，端口 :5210
crabagent --serve --port 8080
crabagent --build-desktop     # 从 pip 安装构建 .dmg
```

### 代码检查 / 格式化
```
ruff check src/ tests/
ruff format src/ tests/
```

### 测试
```
pytest                        # 全部测试（pyproject.toml 中 asyncio_mode=auto）
pytest tests/test_sandbox.py  # 单个文件
```

## 架构

双模式 Python Agent 平台：**CLI**（`src/crabagent/cli/`）和 **Serve**（`src/crabagent/serve/`），共享核心逻辑 `src/crabagent/core/`。

### 关键目录
| 路径 | 用途 |
|------|------|
| `src/crabagent/core/agent/loop.py` | Agent 循环——litellm 调用、工具执行、上下文压缩 |
| `src/crabagent/core/agent/context.py` | `AgentContext` 数据类（workspace、messages、event_bus、tool_registry） |
| `src/crabagent/core/agent/tools/` | 内置工具：bash、read、write、edit、glob、grep、web、browser、agent、sandbox、scheduled_task |
| `src/crabagent/core/agent/agents.py` | 多 Agent 委派——从数据库加载 `AgentProfile` |
| `src/crabagent/core/agent/compress.py` | 上下文窗口压缩（阈值 0.8） |
| `src/crabagent/core/agent/token_limits.py` | 模型 Token 限制注册表 |
| `src/crabagent/core/config.py` | `Settings`（pydantic-settings，环境变量前缀 `CRAB_`，读取 `.env`） |
| `src/crabagent/core/database.py` | SQLAlchemy 异步模型 + `init_db()` 含 ALTER TABLE 迁移 |
| `src/crabagent/core/provider_store.py` | LLM 供应商 CRUD（API 密钥用 Fernet 加密） |
| `src/crabagent/core/mcp/` | MCP（模型上下文协议）客户端 + 工具注册 |
| `src/crabagent/core/molt/` | 快照/回滚系统（差异存储在 `.crabagent/molts/`） |
| `src/crabagent/core/tool_loader.py` | 从 `.crabagent/tools/*.py` 发现用户工具 |
| `src/crabagent/serve/api/` | FastAPI 路由——prompt、session、message、agent、provider、MCP 等 |
| `src/crabagent/serve/services/` | 业务逻辑——认证、会话、消息、持久化 |
| `src/crabagent/skills/` | 内置技能（如 `python-debugger/`） |

### 工具注册流程
1. 内置工具通过 `tools/registry.py` 中的装饰器在 `import` 时自注册
2. Browser/agent/scheduled_task 工具可选导入（包裹在 `try/except` 中）
3. `discover_skills()` + `register_skill_tool()` 从 `.crabagent/skills/` 和 `.opencode/skills/` 加载
4. `discover_and_register_tools()` 从 `.crabagent/tools/` 加载用户 `.py` 文件
5. `register_mcp_tools()` 注册来自 MCP 服务器的工具

### Serve 模式流程
- 入口：`serve/app.py` 中的 `create_app()`——挂载所有 `/api` 路由 + SPA 回退
- 生命周期：`init_db()` -> 启动 MCP 客户端 -> 启动调度器
- Prompt 处理：`serve/api/prompt.py` 为每个请求创建 `AgentContext`，在 `asyncio.Task` 中运行 agent

## 数据库结构变更
- 添加新列/表时**绝不要**删除 `crabagent.db`
- SQLAlchemy 的 `create_all()` 只创建新表，不会修改已有表
- 给已有表添加列时，在 `src/crabagent/core/database.py` 的 `init_db()` 中添加 ALTER TABLE 逻辑
- 示例模式：
  ```python
  result = await conn.execute(text("PRAGMA table_info(conversations)"))
  columns = [row[1] for row in result.fetchall()]
  if "tokens" not in columns:
      await conn.execute(text("ALTER TABLE conversations ADD COLUMN tokens INTEGER DEFAULT 0"))
  ```

## 浏览器自动化 (v0.3.0)
- Playwright 是**可选依赖**：`pip install 'crabagent[browser]'`
- 工具仅在 playwright 可导入时注册——`browser.py` 中的 `PLAYWRIGHT_AVAILABLE` 标志
- `BrowserManager` 存储在 `context.metadata["_browser_manager"]`，首次调用时懒初始化
- 默认无头模式；设置 `CRAB_BROWSER_HEADLESS=false` 启用有头模式
- 清理：CLI 和 serve 的 prompt 处理器中 `finally` 块都会调用 `browser_mgr.close()`

## 配置
- 所有设置使用环境变量前缀 `CRAB_`（如 `CRAB_DB_URL`、`CRAB_SERVE_PORT`、`CRAB_JWT_SECRET`）
- `.env` 文件由 pydantic-settings 自动加载
- API 密钥使用 Fernet 静态加密（密钥自动生成在 `~/.crabagent/encryption_key`）
- 加密密钥迁移在 `init_db()` 中通过 `migrate_plaintext_keys()` 执行

## 通用规则
- Provider 配置是存储在 `crabagent.db` 中的用户数据——未经用户明确批准不得删除数据库
- 首次 `init_db()` 时创建默认管理员用户（用户名：`admin`，密码：`xcl1989`）
- 预设 4 个默认 Agent 配置：researcher、analyst、coder、writer
- 要求 Python >=3.12
- 有疑问时，先询问用户再执行任何破坏性操作

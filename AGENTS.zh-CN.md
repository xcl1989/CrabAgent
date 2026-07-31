# 项目规则

> 此文件会自动加载到每个会话的系统提示词中。
> 保持简洁——最多约 8000 字符。使用 `update_agents_md` 工具来更新。

## 版本
- 当前：**0.12.3**（记忆分层与工作区隔离）
- **版本唯一源头：`pyproject.toml`**
- Python 代码通过 `from crabagent import __version__` 动态读取（`importlib.metadata.version("crabagent")`），自动同步
- Electron `package.json` 需手动运行 `python3 scripts/sync_version.py` 同步
- 修改版本号只需改 `pyproject.toml` 一处，然后运行 `python3 scripts/sync_version.py` 更新 Electron 配置

## Office 文档能力

CrabAgent 通过以下组件处理 Office 文档：

| 组件 | 用途 | 位置 |
|------|------|------|
| **OfficeManager** | OfficeCLI binary 封装（检测/执行/解析/轻量性能统计） | `src/crabagent/core/office/manager.py` |
| **8 个 Agent 工具** | office_read / help / batch_edit / create / edit / query / render | `src/crabagent/core/agent/tools/office.py` |
| **文档管理 API** | 上传/下载/预览/保存/Quick Edit/结构编辑 | `src/crabagent/serve/api/documents.py` |
| **DocumentPanel** | 前端文档面板（预览/时间线/Quick Edit） | `frontend/src/components/DocumentPanel.tsx` |

## 命令

```bash
make install
pip install -e '.[dev]'
ruff check src/ tests/
ruff format src/ tests/
pytest tests
```

前端构建：`cd frontend && npm run build`，之后将 `frontend/dist/index.html` 和 `frontend/dist/assets` 同步至 `src/crabagent/static/`。

## 数据库结构变更
- 添加新列/表时**绝不要**删除 `crabagent.db`。
- 给已有表添加列时，在 `src/crabagent/core/database.py` 的 `init_db()` 中添加 ALTER TABLE 逻辑。

## 协作浏览器
- Electron Bridge：`src/crabagent/electron/main.js`
- Agent 工具：`src/crabagent/core/agent/tools/collaboration_browser.py`
- 前端：`frontend/src/pages/BrowserCollaborationPage.tsx`
- 浏览器任务 API：`src/crabagent/serve/api/browser_tasks.py`
- 协作浏览器会话选择器应保持轻量：不要加载完整会话历史到右侧，仅加载近期少量摘要消息；Agent 后端仍基于完整会话上下文工作。

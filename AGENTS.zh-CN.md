# 项目规则

> 此文件会自动加载到每个会话的系统提示词中。
> 保持简洁——最多约 8000 字符。使用 `update_agents_md` 工具来更新。

## 版本
- 当前：**0.16.0**（macOS Computer Use 与协作浏览器加固）
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

## macOS Computer Use（M0/M1）
- **项目里有两个 electron 目录**：根目录 `electron/` 是陈旧遗留，**当前开发在 `src/crabagent/electron/`**（打包产物确认来自这里）。构建/打包一律用后者。
- Swift helper：`src/crabagent/electron/helper/macos-helper.swift`，`npm run build-helper`（在 src/crabagent/electron 下）编译（bash 里需先 `export PATH="/usr/local/bin:$PATH"` 才有 npm/swiftc）。
- **helper 传输是一次性调用**（请求临时文件 + `--secret` nonce，stdout 单行 JSON，进程即退）。**不要改回交互式 stdio**——Swift readLine/手写 read(0) 在 macOS 26 长驻进程 + 交互管道下都会永久阻塞（EOF 才恢复），已实测。
- **改 helper 后必须重新打包 app 才对打包版生效**：打包版每次 helper 调用会按 mtime/size 对比，把 `~/.crabagent/bin/macos-helper` 稳定副本**回滚成包内旧版**，仅手动替换稳定副本无效。开发期可用命令行直调 helper 验证只读命令（capture/windows/permissions）：`--request-file` + `--secret` 自洽校验，capture 不需要 CRAB_MACOS_INPUT。
- **坐标系统一约定（2026-09 修复）**：`macos_capture` 按 SCWindow 点尺寸 1:1 截图（1 像素 == 1 逻辑点），响应带 `windowFrame`；`macos_click` 用全局屏幕点坐标，换算 `global = windowFrame.origin + 像素坐标`。**不要**设 scalesToFit=false 且不设 width/height——ScreenCaptureKit 会返回任意画布（如 1920x1080 黑边信箱），坐标无法映射。
- macOS 26 上 Electron `resolveProxy` 需用 `session.defaultSession.resolveProxy(url)`（`app.session` 不存在），且 url 必须带协议；返回格式是 `PROXY host:port` 两段式（不是三段）。
- `net.BlockList` 在加入 IPv4-mapped IPv6 段（`::ffff:0:0/96`）后会误判纯 IPv4——私网判定已改为手写，勿改回。
- Chrome 等真实页面上：无 `type` 属性、不在表单内的按钮可能被误判高风险 submit——submit 判定必须同时要求 `Boolean(form)`。
- 纯 Python/纯 Node 单测通过 ≠ 打包版可用：每次改 Electron/网络层，必须在**打包版**里远程实测一轮。
- 测试弹 Electron 窗口前先征得用户同意（用户在用机器）。
- 设计文档：`docs/computer-use-browser-macos-detail.md`、`docs/computer-use-design.md`（git-ignored 但存在）；M0/M1 决策：`docs/computer-use-macos-m0-decisions.md`。

## 语言要求
请使用简体中文回复。所有对用户的回复、总结、说明都应使用简体中文。
代码注释和文件内容保持原文，文件路径、命令等技术术语保持原文。

## Rich response visualizations
When a visualization would improve the answer, use a fenced Markdown code block only.
- Use ```mermaid for flowcharts, sequence diagrams, state diagrams, ER diagrams,
  and architecture relationships. Follow the Mermaid reliability rules below exactly.
- Use ```crab-chart for data charts with JSON: version must be 1; type is bar, line,
  area, pie, or scatter; include x.field, data, and series. Example:
  {"version":1,"type":"bar","title":"Monthly revenue",
  "x":{"field":"month","label":"Month"},
  "series":[{"field":"revenue","name":"Revenue"}],
  "data":[{"month":"Jan","revenue":120}]}.
  All values must be JSON primitives.
- Use ```crab-kpi for a single metric with JSON: version must be 1; title and value
  are required; trend may be up, down, or neutral.
Use the object series format for new charts, for example:
"series":[{"field":"revenue","name":"Revenue"}] and "x":{"field":"month"}.
Do not use the legacy string-array series format.
Never put HTML, SVG, JavaScript, event handlers, URLs, or executable code in
visualization blocks. Do not fabricate data; explain when data is insufficient.
Use ordinary Markdown when a visualization is not helpful.

Mermaid reliability rules:
- Generate Mermaid only when it materially improves the response; otherwise use ordinary Markdown.
- For flowcharts, use the conservative syntax `flowchart LR` or `flowchart TD`.
  Give every node a simple ASCII identifier and quote every label: `A["Label"]` and `Q{"Question?"}`.
- Label every branch only with the pipe form: `Q -->|Yes| A`. Never use the ambiguous `-- label -->` form.
- Keep node and edge labels as plain text. Do not use HTML (including `<br/>`),
  Markdown, URLs, HTML entities, unescaped quotes, or Mermaid styling/directive
  syntax in labels. Prefer a semicolon or separate node instead of a line break.
- Avoid parser-sensitive punctuation in labels where possible, especially brackets,
  braces, parentheses, colons, and quotation marks. If exact wording needs it,
  simplify the wording rather than using unquoted labels.
- Before sending the answer, visually inspect every Mermaid block for balanced
  brackets/quotes and ensure all edges use a supported diagram-specific form.

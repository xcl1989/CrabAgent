# Pipeline 持久化 — 详细设计

> 版本: MVP (v0.9.4)
> 日期: 2026-06-06

---

## 1. 设计决策

### 1.1 存储：YAML 文件（非数据库）

| 对比项 | YAML 文件 | DB 表 |
|--------|-----------|-------|
| 用户直接编辑 | ✅ | ❌ |
| Git 友好 | ✅ 跟着项目走 | ❌ |
| 分享 | ✅ 复制文件即可 | ❌ 需导入导出 |
| 与现有模式一致 | ✅ 和 tools/skills 一样 | ✅ 和 agents/tasks 一样 |
| Web 管理成本 | 需封装读写 | 天然支持 |

**结论**：Pipeline 是项目级可复用工作流定义，本质上是配置而非运行时数据。选 YAML 文件。

Web 管理时直接读写文件，不额外建 DB 表（与 MCP servers 管理不同——MCP 是全局设置存 DB，pipeline 是项目配置存文件）。

### 1.2 作用域：workspace 级，预留全局回退

```
workspace/
  .crabagent/
    tools/         ← 现有
    skills/        ← 现有
    pipelines/     ← 新增
      code-review.yaml
      weekly-report.yaml
```

查找顺序：`workspace/.crabagent/pipelines/` → `~/.crabagent/pipelines/`（全局回退，MVP 不实现）。

### 1.3 MVP 范围

```
✅ 做                         ❌ 暂不做
─────────────────────────────────────────
name + description + steps    参数化 / 变量 {{ xxx }}
YAML 文件存储                  调度集成
run_pipeline_template 工具     错误策略 (continue/abort)
TUI /pipeline 命令             pipeline 组合 (嵌套引用)
API 端点 + Web 列表            分享 / 市场
plan_task 输出 → 可保存         版本管理
```

---

## 2. YAML 格式设计

### 2.1 完整 Schema（MVP 用到的字段标 ✅，预留字段标 🔮）

```yaml
# .crabagent/pipelines/code-review.yaml

name: code-review              # ✅ 唯一标识，snake_case
display_name: 代码审查          # ✅ 显示名
description: 对代码进行多维度审查  # ✅ 描述
# author: admin                # 🔮 预留
# version: "1.0"               # 🔮 预留
# tags: [code, review]         # 🔮 预留

steps:                          # ✅ 核心步骤
  - id: collect                 # ✅ 步骤 ID
    agent_name: researcher      # ✅ Agent 名
    task: 收集以下代码的上下文和变更信息  # ✅ 任务描述
    # depends_on: []            # ✅ 可选，默认 []

  - id: analyze
    agent_name: analyst
    task: 分析代码质量和潜在问题
    depends_on: [collect]

  - id: fix
    agent_name: coder
    task: 基于分析结果提出修复建议
    depends_on: [analyze]

# parameters:                   # 🔮 预留
#   - name: target_files
#     type: string
#     required: true
#     description: 要审查的文件

# schedule:                     # 🔮 预留
#   cron: "0 9 * * 1"

# error_strategy: abort         # 🔮 预留: abort | continue

# timeout:                      # 🔮 预留
#   per_step: 300
#   total: 600
```

### 2.2 MVP 验证规则

```python
REQUIRED_FIELDS = ["name", "steps"]
STEP_REQUIRED = ["id", "agent_name", "task"]
NAME_PATTERN = r"^[a-z][a-z0-9_-]*$"   # 允许连字符
MAX_STEPS = 10
MAX_NAME_LEN = 64
```

### 2.3 最小有效文件示例

```yaml
name: quick-research
display_name: 快速调研
description: 搜索并汇总指定主题
steps:
  - id: search
    agent_name: researcher
    task: 搜索相关信息
  - id: summarize
    agent_name: writer
    task: 汇总搜索结果
    depends_on: [search]
```

---

## 3. 实现设计

### 3.1 新增文件

```
src/crabagent/core/pipeline/
  __init__.py
  loader.py        # YAML 加载 / 验证 / 列举
  runner.py        # run_pipeline_template 工具实现
  builtin.py       # 内置模板种子数据
```

### 3.2 Pipeline Loader (`loader.py`)

```python
"""Pipeline YAML 加载、验证、列举。"""

from __future__ import annotations
import re
from pathlib import Path
from dataclasses import dataclass, field

import yaml

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
MAX_STEPS = 10
MAX_NAME_LEN = 64


@dataclass
class PipelineStep:
    id: str
    agent_name: str
    task: str
    depends_on: list[str] = field(default_factory=list)


@dataclass
class PipelineTemplate:
    name: str
    display_name: str
    description: str
    steps: list[PipelineStep]
    source: str = ""                    # 文件路径，运行时填充

    def to_run_pipeline_steps(self) -> list[dict]:
        """转换为 run_pipeline() 需要的 steps 格式。"""
        return [
            {
                "id": s.id,
                "agent_name": s.agent_name,
                "task": s.task,
                "depends_on": s.depends_on,
            }
            for s in self.steps
        ]


class PipelineError(Exception):
    """Pipeline 加载/验证错误。"""
    pass


def pipeline_dirs(workspace: Path) -> list[Path]:
    """返回 pipeline 搜索路径（workspace 级，未来加全局回退）。"""
    ws_dir = workspace / ".crabagent" / "pipelines"
    # 🔮 全局回退: global_dir = Path.home() / ".crabagent" / "pipelines"
    return [ws_dir]


def list_pipelines(workspace: Path) -> list[PipelineTemplate]:
    """列举所有可用 pipeline。同名时 workspace 级优先。"""
    seen: dict[str, PipelineTemplate] = {}
    for d in pipeline_dirs(workspace):
        if not d.exists():
            continue
        for f in sorted(d.glob("*.yaml")):
            try:
                tpl = load_pipeline(f)
                if tpl.name not in seen:
                    tpl.source = str(f)
                    seen[tpl.name] = tpl
            except PipelineError:
                pass  # 跳过无效文件，不打断其他
    return list(seen.values())


def load_pipeline(path: Path) -> PipelineTemplate:
    """加载并验证单个 pipeline YAML。"""
    if not path.exists():
        raise PipelineError(f"文件不存在: {path}")

    raw = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise PipelineError(f"YAML 解析失败: {e}")

    if not isinstance(data, dict):
        raise PipelineError("YAML 根节点必须是 dict")

    return _validate(data)


def get_pipeline(workspace: Path, name: str) -> PipelineTemplate | None:
    """按 name 查找 pipeline。"""
    for d in pipeline_dirs(workspace):
        path = d / f"{name}.yaml"
        if path.exists():
            return load_pipeline(path)
    return None


def save_pipeline(workspace: Path, tpl: PipelineTemplate) -> Path:
    """保存 pipeline 到 workspace。返回文件路径。"""
    d = pipeline_dirs(workspace)[0]
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{tpl.name}.yaml"

    data = {
        "name": tpl.name,
        "display_name": tpl.display_name,
        "description": tpl.description,
        "steps": [
            {
                "id": s.id,
                "agent_name": s.agent_name,
                "task": s.task,
                **({"depends_on": s.depends_on} if s.depends_on else {}),
            }
            for s in tpl.steps
        ],
    }

    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return path


def delete_pipeline(workspace: Path, name: str) -> bool:
    """删除 pipeline 文件。返回是否成功。"""
    for d in pipeline_dirs(workspace):
        path = d / f"{name}.yaml"
        if path.exists():
            path.unlink()
            return True
    return False


def _validate(data: dict) -> PipelineTemplate:
    name = data.get("name", "")
    if not name:
        raise PipelineError("缺少 'name' 字段")
    if not NAME_RE.match(str(name)):
        raise PipelineError(f"name '{name}' 格式错误，需 snake_case (允许连字符)")
    if len(str(name)) > MAX_NAME_LEN:
        raise PipelineError(f"name 过长 (max {MAX_NAME_LEN})")

    steps_raw = data.get("steps", [])
    if not steps_raw:
        raise PipelineError("steps 不能为空")
    if len(steps_raw) > MAX_STEPS:
        raise PipelineError(f"steps 过多 (max {MAX_STEPS})")

    steps: list[PipelineStep] = []
    ids: set[str] = set()
    for i, s in enumerate(steps_raw):
        if not isinstance(s, dict):
            raise PipelineError(f"step[{i}] 必须是 dict")
        for key in ("id", "agent_name", "task"):
            if key not in s or not s[key]:
                raise PipelineError(f"step[{i}] 缺少 '{key}'")
        if s["id"] in ids:
            raise PipelineError(f"step id '{s['id']}' 重复")
        ids.add(s["id"])

        deps = s.get("depends_on", [])
        for d in deps:
            if d not in ids:
                # 允许前向引用（depends_on 引用后续 step）
                pass

        steps.append(PipelineStep(
            id=str(s["id"]),
            agent_name=str(s["agent_name"]),
            task=str(s["task"]),
            depends_on=[str(x) for x in deps],
        ))

    # 最终检查：所有 depends_on 必须指向存在的 id
    all_ids = {s.id for s in steps}
    for s in steps:
        for d in s.depends_on:
            if d not in all_ids:
                raise PipelineError(f"step '{s.id}' depends_on '{d}' 不存在")

    return PipelineTemplate(
        name=str(name),
        display_name=str(data.get("display_name", name)),
        description=str(data.get("description", "")),
        steps=steps,
    )
```

### 3.3 Pipeline Runner / 工具 (`runner.py`)

```python
"""run_pipeline_template 工具 — 加载 YAML 并调用现有 run_pipeline。"""

from __future__ import annotations

from crabagent.core.agent.tools.registry import registry


@registry.register(
    name="run_pipeline_template",
    description=(
        "Execute a saved pipeline template by name. "
        "The pipeline definition is loaded from .crabagent/pipelines/<name>.yaml. "
        "Use list_pipeline_templates to see available templates."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Pipeline template name (e.g. 'code-review', 'weekly-report')",
            },
        },
        "required": ["name"],
    },
    metadata={"source": "builtin", "category": "agent"},
)
async def run_pipeline_template(name: str, context=None) -> str:
    if context is None:
        return "Error: run_pipeline_template requires an active session"

    from crabagent.core.pipeline.loader import get_pipeline

    tpl = get_pipeline(context.workspace, name)
    if not tpl:
        from crabagent.core.pipeline.loader import list_pipelines
        available = [t.name for t in list_pipelines(context.workspace)]
        names = ", ".join(available) if available else "(none)"
        return f"Error: pipeline '{name}' not found. Available: {names}"

    # 复用现有 run_pipeline
    from crabagent.core.agent.tools.agent import run_pipeline

    steps = tpl.to_run_pipeline_steps()
    return await run_pipeline(steps, context)


@registry.register(
    name="list_pipeline_templates",
    description="List all saved pipeline templates with their steps.",
    parameters={"type": "object", "properties": {}},
    metadata={"source": "builtin", "category": "agent"},
)
async def list_pipeline_templates(context=None) -> str:
    if context is None:
        return "Error: list_pipeline_templates requires an active session"

    from crabagent.core.pipeline.loader import list_pipelines

    templates = list_pipelines(context.workspace)
    if not templates:
        return "No pipeline templates found. Create one with /pipeline save or edit a YAML file in .crabagent/pipelines/."

    lines = ["# Pipeline Templates\n"]
    for t in templates:
        step_count = len(t.steps)
        agents = ", ".join(sorted({s.agent_name for s in t.steps}))
        lines.append(f"**{t.display_name}** (`{t.name}`)")
        lines.append(f"  {t.description}")
        lines.append(f"  Steps: {step_count} | Agents: {agents}")
        lines.append("")

    return "\n".join(lines)


@registry.register(
    name="save_pipeline_template",
    description=(
        "Save a pipeline definition as a reusable template. "
        "The template will be available via run_pipeline_template and /pipeline commands."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Template name in snake_case (e.g. 'code-review')",
            },
            "display_name": {
                "type": "string",
                "description": "Human-readable name (e.g. '代码审查')",
            },
            "description": {
                "type": "string",
                "description": "What this pipeline does",
            },
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "agent_name": {"type": "string"},
                        "task": {"type": "string"},
                        "depends_on": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["id", "agent_name", "task"],
                },
                "description": "Pipeline steps (same format as run_pipeline)",
            },
        },
        "required": ["name", "steps"],
    },
    requires_permission=True,
    metadata={"source": "builtin", "category": "agent"},
)
async def save_pipeline_template(
    name: str,
    steps: list[dict],
    display_name: str = "",
    description: str = "",
    context=None,
) -> str:
    if context is None:
        return "Error: save_pipeline_template requires an active session"

    from crabagent.core.pipeline.loader import (
        PipelineStep, PipelineTemplate, save_pipeline, get_pipeline, _validate,
    )

    # 构造数据走验证
    data = {
        "name": name,
        "display_name": display_name or name,
        "description": description,
        "steps": steps,
    }
    try:
        tpl = _validate(data)
    except Exception as e:
        return f"Error: {e}"

    # 检查覆盖
    existing = get_pipeline(context.workspace, name)
    action = "updated" if existing else "created"

    path = save_pipeline(context.workspace, tpl)
    return (
        f"Pipeline '{name}' {action}.\n"
        f"  File: {path}\n"
        f"  Steps: {len(tpl.steps)}\n"
        f"  Run with: run_pipeline_template(name='{name}')"
    )
```

### 3.4 内置模板 (`builtin.py`)

```python
"""4 个内置 pipeline 模板 — 首次启动时写入 .crabagent/pipelines/。"""

from pathlib import Path

BUILTIN_PIPELINES = {
    "code-review": {
        "name": "code-review",
        "display_name": "代码审查",
        "description": "多维度代码审查：收集上下文 → 分析问题 → 提出修复",
        "steps": [
            {"id": "collect", "agent_name": "researcher", "task": "收集待审查代码的上下文、依赖关系和变更历史"},
            {"id": "analyze", "agent_name": "analyst", "task": "分析代码质量、安全风险和性能问题", "depends_on": ["collect"]},
            {"id": "fix", "agent_name": "coder", "task": "基于分析结果提出具体修复建议和改进方案", "depends_on": ["analyze"]},
        ],
    },
    "competitive-research": {
        "name": "competitive-research",
        "display_name": "竞品调研",
        "description": "竞品信息收集 → 对比分析 → 输出报告",
        "steps": [
            {"id": "search", "agent_name": "researcher", "task": "搜索竞品相关信息、功能特性和市场表现"},
            {"id": "compare", "agent_name": "analyst", "task": "对比分析竞品与自身产品的差异", "depends_on": ["search"]},
            {"id": "report", "agent_name": "writer", "task": "撰写竞品调研报告，包含结论和建议", "depends_on": ["compare"]},
        ],
    },
    "architecture-design": {
        "name": "architecture-design",
        "display_name": "架构设计",
        "description": "需求分析 → 方案设计 → 评审",
        "steps": [
            {"id": "research", "agent_name": "researcher", "task": "收集技术方案相关的需求、约束和参考资料"},
            {"id": "design", "agent_name": "coder", "task": "设计技术方案，包括架构图、接口定义和技术选型", "depends_on": ["research"]},
            {"id": "review", "agent_name": "analyst", "task": "评审技术方案的可行性、风险和改进点", "depends_on": ["design"]},
        ],
    },
    "doc-generation": {
        "name": "doc-generation",
        "display_name": "文档生成",
        "description": "阅读代码 → 生成文档 → 校对",
        "steps": [
            {"id": "read", "agent_name": "researcher", "task": "阅读并理解代码结构和逻辑"},
            {"id": "write", "agent_name": "writer", "task": "根据代码内容生成清晰完整的技术文档", "depends_on": ["read"]},
            {"id": "proofread", "agent_name": "analyst", "task": "校对文档的准确性、完整性和可读性", "depends_on": ["write"]},
        ],
    },
}


def ensure_builtin_pipelines(workspace: Path) -> int:
    """确保内置模板存在。返回新建数量。"""
    import yaml

    pip_dir = workspace / ".crabagent" / "pipelines"
    pip_dir.mkdir(parents=True, exist_ok=True)

    created = 0
    for name, data in BUILTIN_PIPELINES.items():
        path = pip_dir / f"{name}.yaml"
        if path.exists():
            continue
        path.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        created += 1
    return created
```

### 3.5 集成点

#### 3.5.1 `_ensure_workspace_dirs()` — 自动创建 pipelines/ + 种子数据

在 `src/crabagent/core/database.py` 的 `_ensure_workspace_dirs()` 末尾追加：

```python
# Pipeline templates
from crabagent.core.pipeline.builtin import ensure_builtin_pipelines
ensure_builtin_pipelines(ws)
```

#### 3.5.2 工具注册 — 新增到 `agent.py` 或独立文件

方案：`runner.py` 中的三个工具通过 `@registry.register` 装饰器自动注册（与 `custom_tool.py` 模式一致）。只需确保 `runner.py` 被导入即可。

在 `src/crabagent/core/agent/tools/__init__.py` 或工具注册入口添加：

```python
import crabagent.core.pipeline.runner  # noqa: F401 — 注册 pipeline 工具
```

#### 3.5.3 `custom_tool.py` 保留名列表更新

在 `create_tool` 的保留名列表中追加：

```python
"run_pipeline_template",
"list_pipeline_templates",
"save_pipeline_template",
```

---

## 4. TUI /pipeline 命令

### 4.1 命令清单

| 命令 | 说明 |
|------|------|
| `/pipeline` | 列出所有模板 |
| `/pipeline <name>` | 显示模板详情 |
| `/pipeline run <name>` | 执行模板 |
| `/pipeline save <name>` | 保存当前对话中的 pipeline（Agent 通过 save_pipeline_template 工具完成） |
| `/pipeline rm <name>` | 删除模板 |

### 4.2 实现

在 `tui.py` 的 `SLASH_COMMANDS` 追加 `"/pipeline"`，在 `_handle_slash()` 追加分支：

```python
elif cmd == "/pipeline":
    await self._handle_pipeline_slash(arg)
```

```python
async def _handle_pipeline_slash(self, arg: str):
    from crabagent.core.pipeline.loader import list_pipelines, get_pipeline, delete_pipeline

    ws = self.agent_ctx.workspace if self.agent_ctx else Path.cwd()
    parts = arg.split(maxsplit=1)
    sub = parts[0].lower() if parts else ""

    if not sub or sub == "list":
        # 列出
        templates = list_pipelines(ws)
        if not templates:
            self.console.print("[dim]No pipelines. Edit .crabagent/pipelines/*.yaml[/dim]")
            return
        for t in templates:
            agents = ", ".join(sorted({s.agent_name for s in t.steps}))
            self.console.print(f"  [bold]{t.name}[/bold] — {t.display_name} ({len(t.steps)} steps, agents: {agents})")

    elif sub == "run":
        name = parts[1].strip() if len(parts) > 1 else ""
        if not name:
            self.console.print("[dim]/pipeline run <name>[/dim]")
            return
        tpl = get_pipeline(ws, name)
        if not tpl:
            self.console.print(f"[dim]Pipeline '{name}' not found[/dim]")
            return
        # 直接调用工具
        result = await run_pipeline_template(name, context=self.agent_ctx)
        self.console.print(result)

    elif sub == "rm":
        name = parts[1].strip() if len(parts) > 1 else ""
        if not name:
            self.console.print("[dim]/pipeline rm <name>[/dim]")
            return
        if delete_pipeline(ws, name):
            self.console.print(f"[dim]Pipeline '{name}' deleted.[/dim]")
        else:
            self.console.print(f"[dim]Pipeline '{name}' not found.[/dim]")

    elif sub == "save":
        self.console.print("[dim]Use save_pipeline_template tool in conversation to save a pipeline.[/dim]")

    else:
        # /pipeline <name> → 显示详情
        tpl = get_pipeline(ws, sub)
        if not tpl:
            self.console.print(f"[dim]Pipeline '{sub}' not found. Use /pipeline to list.[/dim]")
            return
        self.console.print(f"[bold]{tpl.display_name}[/bold] ({tpl.name})")
        self.console.print(f"  {tpl.description}")
        for i, s in enumerate(tpl.steps, 1):
            deps = f" (after: {', '.join(s.depends_on)})" if s.depends_on else ""
            self.console.print(f"  {i}. {s.agent_name} → {s.task}{deps}")
```

---

## 5. API 端点

### 5.1 新增文件：`src/crabagent/serve/api/pipeline.py`

```python
from __future__ import annotations
import logging
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from crabagent.core.database import User
from crabagent.serve.deps import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pipeline-templates", tags=["pipeline-templates"])


class PipelineStepResponse(BaseModel):
    id: str
    agent_name: str
    task: str
    depends_on: list[str]


class PipelineTemplateResponse(BaseModel):
    name: str
    display_name: str
    description: str
    steps: list[PipelineStepResponse]
    source: str


class SavePipelineRequest(BaseModel):
    name: str
    display_name: str = ""
    description: str = ""
    steps: list[dict]


def _workspace(user: User) -> Path:
    """获取用户的 workspace。简化版：用 cwd。"""
    # 🔮 未来从 user settings 或 session 获取
    return Path.cwd().resolve()


@router.get("", response_model=list[PipelineTemplateResponse])
async def list_templates(user: User = Depends(get_current_user)):
    from crabagent.core.pipeline.loader import list_pipelines
    ws = _workspace(user)
    templates = list_pipelines(ws)
    return [
        PipelineTemplateResponse(
            name=t.name,
            display_name=t.display_name,
            description=t.description,
            steps=[PipelineStepResponse(**s.__dict__) for s in t.steps],
            source=t.source,
        )
        for t in templates
    ]


@router.get("/{name}", response_model=PipelineTemplateResponse)
async def get_template(name: str, user: User = Depends(get_current_user)):
    from crabagent.core.pipeline.loader import get_pipeline
    tpl = get_pipeline(_workspace(user), name)
    if not tpl:
        raise HTTPException(404, f"Pipeline '{name}' not found")
    return PipelineTemplateResponse(
        name=tpl.name,
        display_name=tpl.display_name,
        description=tpl.description,
        steps=[PipelineStepResponse(**s.__dict__) for s in tpl.steps],
        source=tpl.source,
    )


@router.post("", response_model=PipelineTemplateResponse)
async def create_template(req: SavePipelineRequest, user: User = Depends(get_current_user)):
    from crabagent.core.pipeline.loader import get_pipeline, save_pipeline, PipelineStep, PipelineTemplate, _validate
    data = {"name": req.name, "display_name": req.display_name, "description": req.description, "steps": req.steps}
    try:
        tpl = _validate(data)
    except Exception as e:
        raise HTTPException(400, str(e))
    existing = get_pipeline(_workspace(user), req.name)
    if existing:
        raise HTTPException(409, f"Pipeline '{req.name}' already exists. Use PATCH to update.")
    path = save_pipeline(_workspace(user), tpl)
    tpl.source = str(path)
    return PipelineTemplateResponse(
        name=tpl.name, display_name=tpl.display_name, description=tpl.description,
        steps=[PipelineStepResponse(**s.__dict__) for s in tpl.steps], source=str(path),
    )


@router.patch("/{name}", response_model=PipelineTemplateResponse)
async def update_template(name: str, req: SavePipelineRequest, user: User = Depends(get_current_user)):
    from crabagent.core.pipeline.loader import get_pipeline, save_pipeline, delete_pipeline, _validate
    existing = get_pipeline(_workspace(user), name)
    if not existing:
        raise HTTPException(404, f"Pipeline '{name}' not found")
    # 如果改名，删除旧文件
    if req.name != name:
        delete_pipeline(_workspace(user), name)
    data = {"name": req.name, "display_name": req.display_name, "description": req.description, "steps": req.steps}
    try:
        tpl = _validate(data)
    except Exception as e:
        raise HTTPException(400, str(e))
    path = save_pipeline(_workspace(user), tpl)
    return PipelineTemplateResponse(
        name=tpl.name, display_name=tpl.display_name, description=tpl.description,
        steps=[PipelineStepResponse(**s.__dict__) for s in tpl.steps], source=str(path),
    )


@router.delete("/{name}")
async def delete_template(name: str, user: User = Depends(get_current_user)):
    from crabagent.core.pipeline.loader import delete_pipeline
    if not delete_pipeline(_workspace(user), name):
        raise HTTPException(404, f"Pipeline '{name}' not found")
    return {"status": "deleted", "name": name}


@router.post("/{name}/run")
async def run_template(name: str, user: User = Depends(get_current_user)):
    """从 Web 触发执行 pipeline — 创建一个 session 执行。"""
    from crabagent.core.pipeline.loader import get_pipeline
    tpl = get_pipeline(_workspace(user), name)
    if not tpl:
        raise HTTPException(404, f"Pipeline '{name}' not found")

    # 🔮 MVP 简化：通过 scheduled task 机制触发（复用 scheduler._run_agent）
    # 后续做 Web 端实时 SSE 推送
    return {"status": "triggered", "name": name, "steps": len(tpl.steps)}
```

### 5.2 注册路由

在 `app.py` 追加：

```python
from crabagent.serve.api.pipeline import router as pipeline_router
app.include_router(pipeline_router, prefix="/api")
```

---

## 6. 依赖

### 6.1 新增依赖

`pyyaml` — 需加入 `pyproject.toml` 的 `dependencies`。

```toml
dependencies = [
    # ... existing ...
    "pyyaml>=6.0",
]
```

---

## 7. 改动清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `pyproject.toml` | 修改 | 添加 `pyyaml>=6.0` 依赖 |
| `src/crabagent/core/pipeline/__init__.py` | **新增** | 空文件 |
| `src/crabagent/core/pipeline/loader.py` | **新增** | YAML 加载/验证/列举 |
| `src/crabagent/core/pipeline/runner.py` | **新增** | 3 个工具 (run/list/save) |
| `src/crabagent/core/pipeline/builtin.py` | **新增** | 4 个内置模板 |
| `src/crabagent/core/database.py` | 修改 | `_ensure_workspace_dirs()` 追加 pipeline 种子 |
| `src/crabagent/core/agent/tools/custom_tool.py` | 修改 | 保留名列表追加 3 个 |
| `src/crabagent/serve/api/pipeline.py` | **新增** | API 端点 |
| `src/crabagent/serve/app.py` | 修改 | 注册 pipeline_router |
| `src/crabagent/cli/tui.py` | 修改 | `/pipeline` 命令 |

---

## 8. 实施步骤

| 步骤 | 内容 | 预估 |
|------|------|------|
| **Step 1** | `loader.py` + `builtin.py` — YAML 加载、验证、种子数据 | 0.5d |
| **Step 2** | `runner.py` — 3 个工具 + 集成到 registry | 0.5d |
| **Step 3** | `_ensure_workspace_dirs` + `custom_tool.py` + `app.py` 集成 | 0.5d |
| **Step 4** | TUI `/pipeline` 命令 | 0.5d |
| **Step 5** | API 端点 `pipeline.py` | 0.5d |
| **Step 6** | 联调测试（CLI + Web） | 0.5d |
| **合计** | | **~2.5d** |

---

## 9. 与 DeepSeek 讨论的对比

| 讨论点 | DeepSeek 建议 | 本设计选择 |
|--------|--------------|-----------|
| 存储 | YAML 文件 | ✅ 一致 |
| 作用域 | workspace 级 | ✅ 一致 |
| 格式 | name + description + steps | ✅ 一致 |
| 新工具 | `run_saved_pipeline` | 命名为 `run_pipeline_template`（更明确），额外加 `list_pipeline_templates` 和 `save_pipeline_template` |
| CLI 命令 | save, list, run, delete, show | ✅ 一致，通过 TUI `/pipeline` 子命令 |
| Dashboard | 列表展示 | 通过 API 端点支持，前端后续做 |
| 内置模板 | 未提 | 追加 4 个种子模板 |
| plan_task 增强 | 未提 | 不在本 MVP 范围，但 `save_pipeline_template` 可直接接收 plan_task 的 JSON 输出 |
| 验证 | 未提 | 完整的 YAML schema 验证（名称格式、steps 完整性、depends_on 引用检查） |
| 保留名 | 未提 | `custom_tool.py` 保留名列表同步更新 |

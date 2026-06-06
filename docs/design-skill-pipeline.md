# Skill Pipeline 增强 — 详细设计

> 版本: MVP
> 日期: 2026-06-06
> 替代: ~~docs/design-pipeline-persistence.md~~（独立 Pipeline 系统方案，已废弃）

---

## 1. 核心思路

**不建独立 Pipeline 系统，而是增强现有 Skill 体系，让它原生支持多 Agent 流水线。**

理由：
- Skill 是通用的 Agent 概念，任何平台都能理解"加载一段指令"
- Skill 已有完整的持久化、发现、加载机制
- 在 Skill 里写"调子 Agent"本身就能工作，缺的只是**结构化执行**
- 一套体系管两种场景（单 Agent 指导 + 多 Agent 流水线），用户学习成本低

---

## 2. Skill 格式扩展

### 2.1 现有格式

```markdown
---
name: python-debugger
description: "Systematically debug Python code..."
---

# Python Debugger Skill

Step 1: Reproduce → Step 2: Analyze → Step 3: Fix
（纯文本，LLM 自行理解执行）
```

### 2.2 增强后格式

在 frontmatter 新增一个可选字段 `pipeline`：

```markdown
---
name: code-review
description: "多维度代码审查流水线"
pipeline:
  steps:
    - id: collect
      agent_name: researcher
      task: 收集待审查代码的上下文、依赖关系和变更历史
    - id: analyze
      agent_name: analyst
      task: 分析代码质量、安全风险和性能问题
      depends_on: [collect]
    - id: fix
      agent_name: coder
      task: 基于分析结果提出具体修复建议
      depends_on: [analyze]
---

# 代码审查

当用户要求审查代码时，自动执行上述流水线。

也可以在非流水线场景下使用本 skill 的指导原则...
```

### 2.3 规则

| 规则 | 说明 |
|------|------|
| `pipeline` 是可选的 | 没有 pipeline 的 skill 跟以前完全一样，零影响 |
| 有 pipeline 时，skill 正文仍然有效 | 正文作为**补充说明**，注入到执行上下文 |
| frontmatter 用 YAML 解析 | 现有 `_FRONTMATTER_RE` 已支持多行 YAML |
| steps 格式与 `run_pipeline()` 一致 | `id`, `agent_name`, `task`, `depends_on` |

---

## 3. 执行逻辑变化

### 3.1 现有流程

```
用户消息 → Agent 调用 skill(name) 工具 → 返回 Markdown 文本 → Agent 读取后自行执行
```

### 3.2 增强后流程

```
用户消息 → Agent 调用 skill(name) 工具
  ├─ 无 pipeline → 跟以前一样，返回 Markdown 文本
  └─ 有 pipeline → 返回结构化说明 + pipeline JSON，Agent 看到
                    后调 run_pipeline() 执行
```

**关键决策：不自动执行，而是让 Agent 自己决定调用 run_pipeline()。**

理由：
- 保持 Agent 自主性，它可能根据上下文决定不用 pipeline
- 避免 skill 工具突然变成异步长时间操作（现有是同步返回文本）
- 实现最简单，不改架构

### 3.3 skill 工具返回值变化

**无 pipeline（不变）**：
```
<skill_content name="python-debugger">
# Python Debugger Skill
Step 1: Reproduce...
</skill_content>
```

**有 pipeline（增强）**：
```
<skill_content name="code-review">
# 代码审查

当用户要求审查代码时，执行以下 pipeline。

## Pipeline Definition
执行 run_pipeline，传入以下 steps：
```json
{"steps": [
  {"id":"collect","agent_name":"researcher","task":"收集待审查代码的上下文..."},
  {"id":"analyze","agent_name":"analyst","task":"分析代码质量...","depends_on":["collect"]},
  {"id":"fix","agent_name":"coder","task":"提出修复建议","depends_on":["analyze"]}
]}
```

如果用户有特定要求（如只查安全性），可以调整步骤后再执行。
</skill_content>
```

Agent 读到这段内容后，自然会调用 `run_pipeline` 并传入 JSON。这就是**提示词驱动**的方式，不需要改任何执行引擎。

---

## 4. 代码改动

### 4.1 `SkillInfo` 数据类增加 pipeline 字段

文件：`src/crabagent/core/agent/skill/loader.py`

```python
@dataclass
class SkillInfo:
    name: str
    description: str
    content: str
    location: Path
    auxiliary_files: list[Path] = field(default_factory=list)
    pipeline_steps: list[dict] | None = None    # ← 新增
```

### 4.2 frontmatter 解析支持 pipeline

文件：`src/crabagent/core/agent/skill/loader.py` — `parse_skill_md()`

现有解析逻辑是逐行读取 `name:` 和 `description:`。改为用 `yaml.safe_load` 解析整个 frontmatter：

```python
def parse_skill_md(path: Path) -> SkillInfo | None:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None

    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None

    frontmatter_text = match.group(1)
    body = text[match.end():]

    # 用 YAML 解析 frontmatter（替代逐行解析）
    try:
        import yaml
        fm = yaml.safe_load(frontmatter_text)
    except Exception:
        return None

    if not isinstance(fm, dict):
        return None

    name = str(fm.get("name", ""))
    description = str(fm.get("description", ""))

    if not name or not _SKILL_NAME_RE.match(name):
        return None
    if not description:
        return None
    if len(name) > 64:
        return None
    if len(description) > 1024:
        description = description[:1024]

    # 解析 pipeline steps（可选）
    pipeline_steps = None
    pipeline_raw = fm.get("pipeline")
    if isinstance(pipeline_raw, dict):
        steps_raw = pipeline_raw.get("steps", [])
        if isinstance(steps_raw, list) and steps_raw:
            pipeline_steps = _validate_pipeline_steps(steps_raw)

    # ... auxiliary_files 逻辑不变 ...

    return SkillInfo(
        name=name,
        description=description,
        content=body.strip(),
        location=skill_dir,
        auxiliary_files=aux_files,
        pipeline_steps=pipeline_steps,
    )
```

### 4.3 `format_skill_content` 增加 pipeline 渲染

```python
def format_skill_content(skill: SkillInfo) -> str:
    parts = [
        f'<skill_content name="{skill.name}">\n',
        f"# Skill: {skill.name}\n\n",
        skill.content,
    ]

    # ← 新增：pipeline 定义
    if skill.pipeline_steps:
        import json
        parts.append("\n\n## Pipeline Definition\n")
        parts.append("Execute run_pipeline with the following steps:\n```json\n")
        parts.append(json.dumps({"steps": skill.pipeline_steps}, ensure_ascii=False, indent=2))
        parts.append("\n```\n")

    if skill.auxiliary_files:
        parts.append("\n\nAuxiliary files (use read tool to load):")
        for f in skill.auxiliary_files:
            try:
                rel = f.relative_to(skill.location)
                parts.append(f"  - {rel}")
            except ValueError:
                parts.append(f"  - {f}")
    parts.append(f"\n\nSkill directory: {skill.location}")
    parts.append("\n</skill_content>")
    return "\n".join(parts)
```

### 4.4 Pipeline steps 验证函数

```python
def _validate_pipeline_steps(steps: list) -> list[dict]:
    """验证并标准化 pipeline steps。"""
    MAX_STEPS = 10
    if len(steps) > MAX_STEPS:
        return None  # 静默忽略，不阻断 skill 加载

    result = []
    ids = set()
    for s in steps:
        if not isinstance(s, dict):
            continue
        if not all(k in s for k in ("id", "agent_name", "task")):
            continue
        sid = str(s["id"])
        if sid in ids:
            continue
        ids.add(sid)
        step = {
            "id": sid,
            "agent_name": str(s["agent_name"]),
            "task": str(s["task"]),
        }
        deps = s.get("depends_on")
        if deps and isinstance(deps, list):
            step["depends_on"] = [str(d) for d in deps]
        result.append(step)

    # 检查 depends_on 引用
    all_ids = {s["id"] for s in result}
    valid = []
    for s in result:
        bad_deps = [d for d in s.get("depends_on", []) if d not in all_ids]
        if bad_deps:
            continue  # 跳过有无效引用的 step
        valid.append(s)

    return valid if valid else None
```

### 4.5 skill 工具描述增强

在 `register_skill_tool` 中，对有 pipeline 的 skill 标注出来：

```python
available_lines = "\n".join(
    f"  - **{s.name}**: {s.description}"
    + (" [PIPELINE]" if s.pipeline_steps else "")
    for s in sorted(skills.values(), key=lambda s: s.name)
)
```

这样 Agent 在 skill 列表里就能看到哪些 skill 含有 pipeline。

---

## 5. 内置 Pipeline Skill 模板

新增 4 个 skill 目录（与 python-debugger 同级）：

```
src/crabagent/skills/
  python-debugger/SKILL.md          ← 现有
  code-review/SKILL.md              ← 新增
  competitive-research/SKILL.md     ← 新增
  architecture-design/SKILL.md      ← 新增
  doc-generation/SKILL.md           ← 新增
```

### 示例：code-review/SKILL.md

```markdown
---
name: code-review
description: "多维度代码审查：收集上下文 → 分析问题 → 提出修复"
pipeline:
  steps:
    - id: collect
      agent_name: researcher
      task: 收集待审查代码的上下文、依赖关系和变更历史
    - id: analyze
      agent_name: analyst
      task: 分析代码质量、安全风险和性能问题
      depends_on: [collect]
    - id: fix
      agent_name: coder
      task: 基于分析结果提出具体修复建议和改进方案
      depends_on: [analyze]
---

# 代码审查

自动执行多 Agent 代码审查流水线：
1. **researcher** 收集代码上下文
2. **analyst** 进行质量和安全分析
3. **coder** 提出修复方案

适用于 PR review、代码质量检查、安全审计等场景。
```

首次启动时 `_ensure_workspace_dirs()` 会把这些 skill 复制到 `.crabagent/skills/`（现有逻辑已支持）。

---

## 6. 依赖

**唯一新增依赖**：`pyyaml>=6.0`（用于解析 frontmatter 中的 pipeline YAML 块）。

实际上项目可能已有 pyyaml（很多库间接依赖），检查后可能不需要显式添加。

---

## 7. 改动清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `src/crabagent/core/agent/skill/loader.py` | 修改 | SkillInfo 加 pipeline_steps、frontmatter 改 yaml 解析、format 增强、验证函数 |
| `src/crabagent/skills/code-review/SKILL.md` | **新增** | 内置 pipeline skill |
| `src/crabagent/skills/competitive-research/SKILL.md` | **新增** | 内置 pipeline skill |
| `src/crabagent/skills/architecture-design/SKILL.md` | **新增** | 内置 pipeline skill |
| `src/crabagent/skills/doc-generation/SKILL.md` | **新增** | 内置 pipeline skill |
| `pyproject.toml` | 可能修改 | 添加 pyyaml 依赖（如未间接依赖） |

**不需要改动的**：
- ❌ 不需要新模块（无 `core/pipeline/`）
- ❌ 不需要新 API 端点
- ❌ 不需要改 TUI 命令
- ❌ 不需要改 database.py
- ❌ 不需要改 custom_tool.py 保留名
- ❌ 不需要改 app.py 路由

---

## 8. 实施步骤

| 步骤 | 内容 | 预估 |
|------|------|------|
| **Step 1** | `loader.py` 改造 — yaml 解析 + pipeline_steps + format 增强 + 验证 | 0.5d |
| **Step 2** | 4 个内置 pipeline skill 模板 | 0.5d |
| **Step 3** | 联调测试（TUI + Web） | 0.5d |
| **合计** | | **~1.5d** |

对比独立 Pipeline 系统方案的 2.5d，工作量减少 40%。

---

## 9. 与独立 Pipeline 方案的对比

| 维度 | 独立 Pipeline 系统 | Skill Pipeline 增强 |
|------|-------------------|-------------------|
| 新增文件数 | 4 个新模块 + 1 API | 0 个新模块 + 4 个 skill 文件 |
| 改动文件数 | 10 个 | 1-2 个 |
| 工作量 | ~2.5d | ~1.5d |
| 新概念 | YAML pipeline 格式、新工具、新命令 | 无（skill 里加个可选字段） |
| Agent 自动执行 | ✅ `run_pipeline_template` 直接触发 | Agent 看到 JSON 后调 `run_pipeline`（一步之遥） |
| 结构化验证 | ✅ 完整验证 | ✅ 有验证（但不阻断 skill 加载） |
| 可移植性 | ❌ CrabAgent 专有 | ✅ 其他平台当普通 skill 读取 |
| 后续扩展 | 独立演进 | 统一在 skill 体系内 |

### 独立方案的唯一优势

Agent **不需要思考**就能触发执行。`run_pipeline_template("code-review")` 直接跑，而 Skill 方案 Agent 要先读 skill → 看到提示 → 决定调 run_pipeline → 传参。

但这个差距很小：
1. Agent 读 skill 后调 run_pipeline 是确定性动作，不会犹豫
2. 多一步反而给了 Agent 灵活性（根据上下文调整步骤）
3. 省 token 的优势在长对话中才有意义

---

## 10. 未来扩展方向（不变）

| 方向 | 在 Skill 体系内怎么做 |
|------|----------------------|
| 参数化 | frontmatter 加 `parameters` 字段，skill 工具接受参数 |
| 调度集成 | `pipeline.schedule` 字段，scheduled_task 直接引用 skill |
| 错误策略 | `pipeline.error_strategy` 字段 |
| Pipeline 组合 | 一个 skill 的 pipeline step 引用另一个 skill |
| 分享 | 直接分享 skill 文件夹 |

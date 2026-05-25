from __future__ import annotations

import logging

from crabagent.core.agent.tools.registry import registry

logger = logging.getLogger(__name__)


@registry.register(
    name="delegate_task",
    description=(
        "Delegate a task to a specialized sub-agent. "
        "The sub-agent works independently with its own tools and reports back. "
        "Use for research, analysis, coding, writing, or any task that benefits from a dedicated expert. "
        "Multiple delegates can be called in sequence for multi-step workflows."
    ),
    parameters={
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": (
                    "Name of the agent to delegate to "
                    "(e.g., 'researcher', 'analyst', 'coder', 'writer'). "
                    "Use list_agents to see available agents."
                ),
            },
            "task": {
                "type": "string",
                "description": "The task description for the sub-agent. Be specific about what you need.",
            },
        },
        "required": ["agent_name", "task"],
    },
    metadata={"source": "builtin", "category": "agent"},
)
async def delegate_task(agent_name: str, task: str, context=None) -> str:
    if context is None:
        return "Error: agent delegation requires an active session"
    from crabagent.core.agent.agents import spawn_sub_agent
    return await spawn_sub_agent(agent_name, task, context)


@registry.register(
    name="list_agents",
    description="List all available agent team members with their roles, goals, and capabilities.",
    parameters={"type": "object", "properties": {}},
    metadata={"source": "builtin", "category": "agent"},
)
async def list_agents() -> str:
    from crabagent.core.agent.agents import load_agent_registry

    agents = await load_agent_registry()
    if not agents:
        return "No agents available."

    lines = ["# Agent Team\n"]
    for a in agents:
        lines.append(f"**{a['display_name']}** (`{a['name']}`)")
        lines.append(f"  Role: {a['role']}")
        lines.append(f"  Goal: {a['goal']}")
        if a.get("model"):
            lines.append(f"  Model: {a['model']}")
        lines.append("")
    return "\n".join(lines)


@registry.register(
    name="handoff_to",
    description=(
        "Hand off the current task to another agent. "
        "The receiving agent continues the work based on the conversation so far. "
        "Use when another agent's expertise is better suited for the next step."
    ),
    parameters={
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "Name of the agent to hand off to",
            },
            "summary": {
                "type": "string",
                "description": "Summary of what has been done so far and what needs to be done next",
            },
        },
        "required": ["agent_name", "summary"],
    },
    metadata={"source": "builtin", "category": "agent"},
)
async def handoff_to(agent_name: str, summary: str, context=None) -> str:
    if context is None:
        return "Error: agent handoff requires an active session"
    from crabagent.core.agent.agents import spawn_sub_agent
    return await spawn_sub_agent(agent_name, summary, context, include_history=True)


@registry.register(
    name="delegate_parallel",
    description=(
        "Delegate multiple tasks to different agents in parallel. "
        "All agents run simultaneously and results are collected. "
        "Use for independent tasks that can benefit from different expertise at the same time."
    ),
    parameters={
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "agent_name": {"type": "string", "description": "Name of the agent"},
                        "task": {"type": "string", "description": "Task description"},
                    },
                    "required": ["agent_name", "task"],
                },
                "description": "List of {agent_name, task} objects to execute in parallel",
            },
        },
        "required": ["tasks"],
    },
    metadata={"source": "builtin", "category": "agent"},
)
async def delegate_parallel(tasks: list[dict], context=None) -> str:
    if context is None:
        return "Error: parallel delegation requires an active session"

    import asyncio

    from crabagent.core.agent.agents import spawn_sub_agent

    if not tasks:
        return "Error: empty task list"

    coros = [spawn_sub_agent(t["agent_name"], t["task"], context) for t in tasks]
    results = await asyncio.gather(*coros, return_exceptions=True)

    lines = [f"# Parallel Delegation Results ({len(results)} agents)\n"]
    for t, r in zip(tasks, results):
        agent = t["agent_name"]
        if isinstance(r, Exception):
            lines.append(f"**{agent}**: Error - {r}")
        else:
            lines.append(f"**{agent}**:\n{r}")
        lines.append("")
    return "\n".join(lines)


@registry.register(
    name="request_help",
    description=(
        "Request help from another agent when you encounter something beyond your expertise. "
        "Use this when your current task requires different skills. "
        "The helper agent works independently and returns results to you."
    ),
    parameters={
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "Name of the agent to ask for help",
            },
            "question": {
                "type": "string",
                "description": "Clear description of what you need help with",
            },
        },
        "required": ["agent_name", "question"],
    },
    metadata={"source": "builtin", "category": "agent"},
)
async def request_help(agent_name: str, question: str, context=None) -> str:
    if context is None:
        return "Error: request_help requires an active session"
    depth = context.metadata.get("_sub_agent_depth", 0)
    if depth >= 1:
        return "Error: cannot request help (maximum nesting depth reached)"
    from crabagent.core.agent.agents import spawn_sub_agent
    return await spawn_sub_agent(agent_name, question, context)


@registry.register(
    name="run_pipeline",
    description=(
        "Run a multi-step agent pipeline with dependencies between steps. "
        "Steps without dependencies run in parallel; steps with depends_on wait for those to finish first. "
        "Each step's result is automatically saved to shared workspace for subsequent steps. "
        "Use for complex multi-step workflows that need coordinated execution."
    ),
    parameters={
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Unique identifier for this step, e.g. 'research', 'analyze', 'implement'",
                        },
                        "agent_name": {
                            "type": "string",
                            "description": "Name of the agent to run for this step",
                        },
                        "task": {
                            "type": "string",
                            "description": "Task description for this step",
                        },
                        "depends_on": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of step IDs that must complete before this step runs",
                        },
                    },
                    "required": ["id", "agent_name", "task"],
                },
                "description": "Ordered list of pipeline steps with optional dependencies",
            },
        },
        "required": ["steps"],
    },
    metadata={"source": "builtin", "category": "agent"},
)
async def run_pipeline(steps: list[dict], context=None) -> str:
    if context is None:
        return "Error: run_pipeline requires an active session"
    if not steps:
        return "Error: empty pipeline"

    import asyncio

    from crabagent.core.agent.agents import spawn_sub_agent
    from crabagent.core.event import AgentEvent, EventType

    step_map = {s["id"]: s for s in steps}
    results: dict[str, str] = {}

    deps: dict[str, set[str]] = {}
    for s in steps:
        sid = s["id"]
        deps[sid] = set(s.get("depends_on") or [])

    await context.event_bus.emit(AgentEvent(
        type=EventType.PIPELINE_START,
        data={"total_steps": len(steps), "step_ids": list(step_map.keys())},
    ))

    completed: set[str] = set()
    failed: set[str] = set()

    while len(completed) + len(failed) < len(steps):
        ready = []
        for sid in step_map:
            if sid in completed or sid in failed:
                continue
            if deps[sid].issubset(completed):
                ready.append(sid)

        if not ready:
            remaining = [sid for sid in step_map if sid not in completed and sid not in failed]
            if remaining:
                failed.update(remaining)
                for sid in remaining:
                    results[sid] = f"Error: unresolved dependencies (depends on {deps[sid] - completed})"
            break

        async def _run_step(sid: str) -> tuple[str, str]:
            step = step_map[sid]
            dep_context = ""
            for dep_id in sorted(deps[sid]):
                if dep_id in results:
                    dep_context += f"\n### Result from step '{dep_id}':\n{results[dep_id][:1500]}\n"

            task_text = step["task"]
            if dep_context:
                task_text = f"{task_text}\n\n## Dependency Results{dep_context}"

            await context.event_bus.emit(AgentEvent(
                type=EventType.PIPELINE_STEP_START,
                data={"step_id": sid, "agent_name": step["agent_name"], "task": step["task"][:200]},
            ))

            result = await spawn_sub_agent(step["agent_name"], task_text, context)

            await context.event_bus.emit(AgentEvent(
                type=EventType.PIPELINE_STEP_END,
                data={"step_id": sid, "agent_name": step["agent_name"], "result": result[:500]},
            ))
            return sid, result

        coros = [_run_step(sid) for sid in ready]
        step_results = await asyncio.gather(*coros, return_exceptions=True)

        for sid, sr in zip(ready, step_results):
            if isinstance(sr, Exception):
                failed.add(sid)
                results[sid] = f"Error: {sr}"
            else:
                _, result = sr
                completed.add(sid)
                results[sid] = result

    await context.event_bus.emit(AgentEvent(
        type=EventType.PIPELINE_END,
        data={"completed": list(completed), "failed": list(failed), "total": len(steps)},
    ))

    lines = [f"# Pipeline Results ({len(completed)}/{len(steps)} succeeded)\n"]
    for s in steps:
        sid = s["id"]
        status = "OK" if sid in completed else "FAIL"
        lines.append(f"## Step: {sid} [{status}]")
        lines.append(f"Agent: {s['agent_name']}")
        if sid in results:
            lines.append(results[sid])
        lines.append("")
    return "\n".join(lines)


@registry.register(
    name="plan_task",
    description=(
        "Analyze a complex task and produce an execution plan with agent assignments. "
        "Does NOT execute anything — only returns a plan. "
        "After getting the plan, use `run_pipeline` (or `delegate_parallel` for independent steps) to execute. "
        "Use this when you're unsure which agents to involve or how to break down a complex task."
    ),
    parameters={
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The complex task to plan. Be specific.",
            },
        },
        "required": ["task"],
    },
    metadata={"source": "builtin", "category": "agent"},
)
async def plan_task(task: str, context=None) -> str:
    if context is None:
        return "Error: plan_task requires an active session"

    import json as _json

    from crabagent.core.agent.agents import load_agent_registry

    agents = await load_agent_registry()
    if not agents:
        return "Error: no agents available. Use list_agents."

    agent_lines = []
    for a in agents:
        tools_info = f" Tools: {', '.join(a.get('tools', []))}" if a.get("tools") else ""
        agent_lines.append(
            f"- **{a['display_name']}** (`{a['name']}`): {a['role']}. {a['goal']}{tools_info}"
        )
    agent_text = "\n".join(agent_lines)

    plan_prompt = (
        "You are a task planner. Break this task into steps for specialized agents.\n\n"
        f"## Available Agents\n{agent_text}\n\n"
        f"## Task\n{task}\n\n"
        "Rules:\n"
        "1. Each step uses one available agent\n"
        "2. Independent steps run in parallel; use depends_on for ordering\n"
        "3. Be specific in each step's task description\n"
        "4. Use 1-5 steps\n\n"
        'Output ONLY a JSON array:\n'
        '[{"id":"s1","agent_name":"researcher","task":"search X","depends_on":[]}]\n'
        "No other text before or after."
    )

    try:
        import litellm

        from crabagent.core.provider_store import get_default_provider, get_provider

        if context.provider_name:
            provider = await get_provider(context.provider_name)
        else:
            provider = await get_default_provider()
        if not provider:
            return "Error: no provider configured"

        llm_params = {"api_key": provider.api_key}
        if provider.base_url:
            llm_params["api_base"] = provider.base_url

        model = context.model or "gpt-4"

        response = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": plan_prompt}],
            max_tokens=1000,
            temperature=0.3,
            **llm_params,
        )

        text = response.choices[0].message.content.strip()

        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            text = text[start:end]

        steps = _json.loads(text)

        agent_names = {a["name"] for a in agents}
        plan_lines = ["# Task Plan\n"]
        for i, s in enumerate(steps):
            aname = s["agent_name"]
            stask = s["task"]
            deps = s.get("depends_on", [])

            if aname not in agent_names:
                return f"Error: unknown agent '{aname}'. Available: {', '.join(agent_names)}"

            dep_str = f" (after: {', '.join(deps)})" if deps else ""
            plan_lines.append(f"{i + 1}. **{aname}** → {stask}{dep_str}")

        plan_lines.append("")
        plan_lines.append("Execute with `run_pipeline`:")
        plan_lines.append("```json")
        plan_lines.append(_json.dumps({"steps": steps}, ensure_ascii=False, indent=2))
        plan_lines.append("```")
        return "\n".join(plan_lines)
    except Exception as e:
        logger.debug("plan_task failed: %s", e, exc_info=True)
        return f"Error planning task: {e}"

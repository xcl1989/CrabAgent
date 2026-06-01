from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def discover_and_register_tools(registry, workspace: Path) -> None:
    tools_dir = workspace / ".crabagent" / "tools"
    if not tools_dir.exists():
        return

    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        _load_tool_file(py_file, registry)


def _load_tool_file(path: Path, registry) -> None:
    try:
        spec = importlib.util.spec_from_file_location(f"_crab_tool_{path.stem}", str(path))
        if not spec or not spec.loader:
            logger.warning("Skipping %s: could not load spec", path.name)
            return

        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)

        name = getattr(mod, "name", None)
        description = getattr(mod, "description", None)
        parameters = getattr(mod, "parameters", None)
        run_fn = getattr(mod, "run", None)
        requires_permission = getattr(mod, "requires_permission", True)
        if not isinstance(requires_permission, bool):
            requires_permission = True

        if not name or not run_fn:
            logger.warning("Skipping %s: missing 'name' or 'run'", path.name)
            return
        if not isinstance(name, str) or not name.strip():
            logger.warning("Skipping %s: 'name' must be a non-empty string", path.name)
            return
        if not parameters:
            parameters = {
                "type": "object",
                "properties": {},
            }

        if not hasattr(run_fn, "_is_registered"):
            wrapped = _make_tool_handler(run_fn)

            registry.register(
                name=name,
                description=description or f"Custom tool from {path.name}",
                parameters=parameters,
                requires_permission=requires_permission,
            )(wrapped)

            run_fn._is_registered = True
            logger.info("Registered custom tool '%s' from %s", name, path.name)

    except Exception as e:
        logger.warning("Failed to load custom tool %s: %s", path.name, e)


def _make_tool_handler(run_fn):
    import inspect

    inspect.signature(run_fn)
    is_async = inspect.iscoroutinefunction(run_fn)

    if is_async:

        async def handler(**kwargs: Any) -> str:
            kwargs.pop("context", None)
            try:
                result = run_fn(**kwargs)
                if inspect.isawaitable(result):
                    result = await result
                return str(result)
            except Exception as e:
                return f"Error: {e}"
    else:

        def handler(**kwargs: Any) -> str:
            kwargs.pop("context", None)
            try:
                return str(run_fn(**kwargs))
            except Exception as e:
                return f"Error: {e}"

    return handler

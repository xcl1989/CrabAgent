"""PyInstaller runtime hook for CrabAgent.

Ensures tiktoken can find its encoding plugins in a frozen (PyInstaller) environment.
tiktoken/registry.py uses pkgutil.iter_modules() to discover plugins, which doesn't
work in PyInstaller's frozen app because there's no real filesystem to iterate.
"""

import tiktoken_ext.openai_public

# Patch registry so even if pkgutil.iter_modules fails, we still find our plugin
import tiktoken.registry as _tiktoken_registry
import tiktoken_ext

_orig_find = _tiktoken_registry._available_plugin_modules

@_tiktoken_registry.functools.lru_cache
def _patched_find():
    mods = list(_orig_find())
    if not mods:
        # Fallback for frozen app: plugins are already loaded
        mods.append("tiktoken_ext.openai_public")
    return mods

_tiktoken_registry._available_plugin_modules = _patched_find

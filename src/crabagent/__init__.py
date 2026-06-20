import os

os.environ.setdefault("LITELLM_LOG", "ERROR")
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from crabagent.core.config import settings


def _resolve_version() -> str:
    """Resolve package version with multiple fallbacks for frozen environments."""
    # 1. Try importlib.metadata (works in normal pip install)
    try:
        from importlib.metadata import version as _metadata_version
        return _metadata_version("crabagent")
    except Exception:
        pass
    # 2. Try reading from bundled VERSION file (PyInstaller frozen)
    try:
        import sys
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for candidate in (
            os.path.join(base, "VERSION"),
            os.path.join(base, "_internal", "VERSION"),
            os.path.join(os.path.dirname(__file__), "VERSION"),
        ):
            if os.path.exists(candidate):
                with open(candidate) as f:
                    return f.read().strip()
    except Exception:
        pass
    # 3. Last resort fallback
    return "0.0.0"


__version__ = _resolve_version()
__all__ = ["settings", "__version__"]

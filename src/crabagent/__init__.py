import os

os.environ.setdefault("LITELLM_LOG", "ERROR")
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from crabagent.core.config import settings

__all__ = ["settings"]

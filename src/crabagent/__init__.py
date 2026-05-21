import os

os.environ.setdefault("LITELLM_LOG", "ERROR")

from crabagent.core.config import settings

__all__ = ["settings"]

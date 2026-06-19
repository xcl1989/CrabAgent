import os
from importlib.metadata import version as _metadata_version

os.environ.setdefault("LITELLM_LOG", "ERROR")
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from crabagent.core.config import settings

__version__ = _metadata_version("crabagent")
__all__ = ["settings", "__version__"]

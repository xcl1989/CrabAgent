"""Desktop pet package support for CrabAgent.

Provides storage helpers and the canonical pet contract used by both the
built-in SVG pet and custom Codex-compatible sprite packages.
"""

from .models import PetAnimationName, PetConfig, PetState
from .store import PetStore, get_pet_store, get_pets_dir

__all__ = [
    "PetAnimationName",
    "PetConfig",
    "PetState",
    "PetStore",
    "get_pet_store",
    "get_pets_dir",
]
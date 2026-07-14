"""Filesystem storage for pet packages.

Pet packages live under ``~/.crabagent/pets/<pet-id>/`` and contain
``pet.json`` plus a spritesheet image (``spritesheet.webp`` or
``spritesheet.png``).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import BinaryIO

from crabagent.core.config import settings

PET_CONFIG_NAME = "pet.json"


def get_pets_dir() -> Path:
    """Return the root directory that holds all pet packages."""
    ws = settings.workspace.resolve()
    if ws == Path("/"):
        ws = Path.home()
    return ws / ".crabagent" / "pets"


class PetStore:
    """Simple filesystem store for pet package assets."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or get_pets_dir()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def package_dir(self, pet_id: str) -> Path:
        return self.root / pet_id

    def config_path(self, pet_id: str) -> Path:
        return self.package_dir(pet_id) / PET_CONFIG_NAME

    def spritesheet_path(self, pet_id: str, filename: str = "spritesheet.webp") -> Path:
        return self.package_dir(pet_id) / filename

    def original_path(self, pet_id: str, filename: str) -> Path:
        """Return a path for an unprocessed image used to build a pet."""
        return self.package_dir(pet_id) / "originals" / filename

    def save_original_image(self, pet_id: str, filename: str, image: object) -> Path:
        """Save a PIL image before background removal, cropping, or atlas packing."""
        path = self.original_path(pet_id, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, "PNG")
        return path

    def exists(self, pet_id: str) -> bool:
        return self.config_path(pet_id).exists()

    def read_config(self, pet_id: str) -> dict:
        path = self.config_path(pet_id)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_config(self, pet_id: str, config: dict) -> None:
        path = self.config_path(pet_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    def write_spritesheet(
        self,
        pet_id: str,
        data: BinaryIO | bytes,
        filename: str = "spritesheet.webp",
    ) -> Path:
        path = self.spritesheet_path(pet_id, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            with path.open("wb") as f:
                shutil.copyfileobj(data, f)
        return path

    def delete_package(self, pet_id: str) -> bool:
        path = self.package_dir(pet_id)
        if not path.exists():
            return False
        shutil.rmtree(path)
        return True


_pet_store: PetStore | None = None


def get_pet_store() -> PetStore:
    global _pet_store
    if _pet_store is None:
        _pet_store = PetStore()
    return _pet_store
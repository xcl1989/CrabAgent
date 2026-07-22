from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from crabagent.core.pets.models import PetConfig
from crabagent.serve.api import pets


class _Result:
    def __init__(self, row):
        self.row = row

    def scalar_one_or_none(self):
        return self.row


class _Db:
    def __init__(self, pet):
        self.pet = pet
        self.committed = False

    async def execute(self, _statement):
        return _Result(self.pet)

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_rename_pet_updates_database_and_manifest(monkeypatch: pytest.MonkeyPatch):
    config = PetConfig(id="gen-123", displayName="gen 123")
    pet = SimpleNamespace(
        pet_id="gen-123",
        display_name="gen 123",
        description="A cat",
        spritesheet_filename="spritesheet.png",
        config_json=config.model_dump_json(),
        is_builtin=False,
    )
    db = _Db(pet)
    written = {}

    monkeypatch.setattr(
        pets,
        "_store",
        lambda: SimpleNamespace(write_config=lambda pet_id, value: written.update({pet_id: value})),
    )

    result = await pets.rename_pet(
        "gen-123",
        pets.RenamePetRequest(displayName="  Mochi  "),
        user=SimpleNamespace(id=1),
        db=db,
    )

    assert result.displayName == "Mochi"
    assert pet.display_name == "Mochi"
    assert PetConfig.model_validate_json(pet.config_json).displayName == "Mochi"
    assert written["gen-123"]["displayName"] == "Mochi"
    assert db.committed is True


@pytest.mark.asyncio
async def test_rename_pet_rejects_blank_name():
    with pytest.raises(HTTPException, match="Pet name must not be empty"):
        await pets.rename_pet(
            "gen-123",
            SimpleNamespace(displayName="   "),
            user=SimpleNamespace(id=1),
            db=_Db(None),
        )

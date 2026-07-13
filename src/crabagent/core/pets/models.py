"""Canonical desktop pet contract.

Codex-compatible sprite packages use an 8x9 grid of 192x208 cells with 9
animation rows. CrabAgent extends this with a small amount of metadata so
that the same runtime can render built-in SVG pets and custom sprite pets.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class PetAnimationName(StrEnum):
    """Animation rows supported by the CrabAgent pet runtime.

    These match the Codex pet contract so custom packages can be dropped in
    without modification.
    """

    IDLE = "idle"
    RUNNING_RIGHT = "running-right"
    RUNNING_LEFT = "running-left"
    WAVING = "waving"
    JUMPING = "jumping"
    FAILED = "failed"
    WAITING = "waiting"
    RUNNING = "running"
    REVIEW = "review"


# A state can be one of the canonical animation rows. Runtime-specific aliases
# such as "working" map to "running" for sprite pets.
PetState = Literal[
    "idle",
    "running-right",
    "running-left",
    "waving",
    "jumping",
    "failed",
    "waiting",
    "running",
    "review",
]


class PetConfig(BaseModel):
    """Manifest inside a pet package (matches Codex pet.json shape)."""

    id: str = Field(..., description="Unique pet identifier used in URLs and storage.")
    displayName: str = Field(..., description="Human-readable name shown in the UI.")
    description: str = Field(default="", description="Optional description.")
    spritesheetPath: str = Field(
        default="spritesheet.webp",
        description="Filename of the spritesheet inside the package folder.",
    )
    width: int = Field(default=192, description="Frame width in pixels.")
    height: int = Field(default=208, description="Frame height in pixels.")
    columns: int = Field(default=8, description="Number of columns in the atlas.")
    rows: int = Field(default=9, description="Number of rows / animation states.")
    frame_counts: dict[PetAnimationName, int] = Field(
        default_factory=lambda: {
            PetAnimationName.IDLE: 6,
            PetAnimationName.RUNNING_RIGHT: 8,
            PetAnimationName.RUNNING_LEFT: 8,
            PetAnimationName.WAVING: 4,
            PetAnimationName.JUMPING: 5,
            PetAnimationName.FAILED: 8,
            PetAnimationName.WAITING: 6,
            PetAnimationName.RUNNING: 6,
            PetAnimationName.REVIEW: 6,
        },
        description="Number of non-empty frames per animation row.",
    )
    frame_rates: dict[PetAnimationName, int] = Field(
        default_factory=lambda: {
            PetAnimationName.IDLE: 150,
            PetAnimationName.RUNNING_RIGHT: 100,
            PetAnimationName.RUNNING_LEFT: 100,
            PetAnimationName.WAVING: 140,
            PetAnimationName.JUMPING: 120,
            PetAnimationName.FAILED: 140,
            PetAnimationName.WAITING: 160,
            PetAnimationName.RUNNING: 120,
            PetAnimationName.REVIEW: 140,
        },
        description="Milliseconds per frame.",
    )
    type: Literal["svg", "spritesheet"] = Field(
        default="spritesheet",
        description="Rendering backend. 'svg' is reserved for the built-in pet.",
    )

    class Config:
        extra = "allow"
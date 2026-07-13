#!/usr/bin/env python3
"""Create a minimal test pet package for local development.

Generates a 1536x1872 spritesheet with colored placeholder frames so the
SpritePet renderer can be exercised without an image generation API key.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw


def main() -> int:
    root = Path.home() / ".crabagent" / "pets" / "test-pixel"
    root.mkdir(parents=True, exist_ok=True)

    width, height = 192, 208
    cols, rows = 8, 9
    img = Image.new("RGBA", (width * cols, height * rows), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    colors = [
        (255, 100, 100),
        (100, 255, 100),
        (100, 100, 255),
        (255, 255, 100),
        (255, 100, 255),
        (100, 255, 255),
        (255, 150, 100),
        (150, 100, 255),
        (100, 255, 150),
    ]

    for row in range(rows):
        for col in range(cols):
            x = col * width
            y = row * height
            color = colors[row]
            # Draw a simple character shape: circle head + rectangle body.
            cx = x + width // 2
            cy = y + height // 2 + 10
            draw.ellipse([cx - 35, cy - 75, cx + 35, cy - 5], fill=(*color, 220))
            draw.rounded_rectangle([cx - 30, cy - 5, cx + 30, cy + 70], radius=10, fill=(*color, 180))
            # Eyes
            draw.ellipse([cx - 15, cy - 55, cx - 5, cy - 45], fill=(255, 255, 255, 230))
            draw.ellipse([cx + 5, cy - 55, cx + 15, cy - 45], fill=(255, 255, 255, 230))
            draw.ellipse([cx - 12, cy - 52, cx - 8, cy - 48], fill=(30, 30, 30, 230))
            draw.ellipse([cx + 8, cy - 52, cx + 12, cy - 48], fill=(30, 30, 30, 230))
            # Frame label
            draw.text((x + 8, y + 8), f"R{row}F{col}", fill=(255, 255, 255, 180))

    sheet_path = root / "spritesheet.png"
    img.save(sheet_path)

    config = {
        "id": "test-pixel",
        "displayName": "Test Pixel Pet",
        "description": "A placeholder spritesheet for testing the pet renderer.",
        "spritesheetPath": "spritesheet.png",
        "width": width,
        "height": height,
        "columns": cols,
        "rows": rows,
        "frame_counts": {
            "idle": 6,
            "running-right": 8,
            "running-left": 8,
            "waving": 4,
            "jumping": 5,
            "failed": 8,
            "waiting": 6,
            "running": 6,
            "review": 6,
        },
        "frame_rates": {
            "idle": 200,
            "running-right": 120,
            "running-left": 120,
            "waving": 160,
            "jumping": 140,
            "failed": 180,
            "waiting": 200,
            "running": 140,
            "review": 180,
        },
        "type": "spritesheet",
    }
    (root / "pet.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"Test pet created at {root}")
    print('Import it via Settings → Pets → "New Pet" with id "test-pixel", then upload spritesheet.png')
    return 0


if __name__ == "__main__":
    sys.exit(main())
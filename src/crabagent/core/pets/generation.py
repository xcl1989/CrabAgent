"""AI spritesheet generation pipeline.

Generates Codex-compatible pet packages (pet.json + spritesheet.png) from a
text prompt. The pipeline mirrors the hatch-pet skill with CrabAgent extras:

1. Generate a base reference image from the user's description.
2. For each animation state, generate a horizontal strip of frames.  A layout
   guide is produced for multi-frame rows and attached as a visual reference.
3. Extract individual frames from each strip with a three-layer strategy:
   - Layer 1: Connected-components grouping (robust against uneven spacing)
   - Layer 2: Stable-slots fallback (shared viewport prevents size popping)
   - Layer 3: Cross-correlation alignment (for stationary rows)
4. Compose the final 1536×1872 atlas.
5. Write pet.json + spritesheet.png into the pet package folder.
6. Persist a PetPackage database record.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
from typing import Any

import httpx
from PIL import Image, ImageChops

from crabagent.core.pets.models import PetAnimationName, PetConfig
from crabagent.core.pets.store import PetStore

logger = logging.getLogger(__name__)

# ── Atlas geometry ────────────────────────────────────────────────────────
CELL_W = 192
CELL_H = 208
COLS = 8
ROWS = 9
ATLAS_W = CELL_W * COLS  # 1536

# Generated strips often bleed into adjacent panels. Keep a small inner gutter
# when splitting, then use the row-wide bounding box to scale the complete pose
# into each atlas cell without mixing two frames together.
SOURCE_FRAME_GUTTER_RATIO = 0.04

# Standard frame counts per row (matches Codex reference).
FRAME_COUNTS: dict[PetAnimationName, int] = {
    PetAnimationName.IDLE: 6,
    PetAnimationName.RUNNING_RIGHT: 8,
    PetAnimationName.RUNNING_LEFT: 8,
    PetAnimationName.WAVING: 4,
    PetAnimationName.JUMPING: 5,
    PetAnimationName.FAILED: 8,
    PetAnimationName.WAITING: 6,
    PetAnimationName.RUNNING: 6,
    PetAnimationName.REVIEW: 6,
    PetAnimationName.THINKING: 6,
    PetAnimationName.TYPING: 6,
    PetAnimationName.READING: 6,
    PetAnimationName.SEARCHING: 6,
    PetAnimationName.TOOL_USING: 6,
    PetAnimationName.CELEBRATE: 6,
    PetAnimationName.SLEEP: 6,
    PetAnimationName.SURPRISED: 4,
    PetAnimationName.CONFUSED: 6,
    PetAnimationName.PET: 4,
}

# Human-readable animation descriptions for image generation prompts.
ANIMATION_PROMPTS: dict[PetAnimationName, str] = {
    PetAnimationName.IDLE: (
        "a resting idle pose, facing forward; keep both feet and the full body locked "
        "in exactly the same horizontal position, with no swaying or lateral motion"
    ),
    PetAnimationName.RUNNING_RIGHT: "running to the right, body facing right, legs in motion",
    PetAnimationName.RUNNING_LEFT: "running to the left, body facing left, legs in motion",
    PetAnimationName.WAVING: "waving greeting, one arm raised, friendly gesture",
    PetAnimationName.JUMPING: "jumping up playfully, mid-air pose, excitement",
    PetAnimationName.FAILED: "sad or confused expression, slumped posture, error state",
    PetAnimationName.WAITING: "waiting patiently, looking forward, arms crossed or hands together",
    PetAnimationName.RUNNING: "working at a desk, typing or thinking, focused expression",
    PetAnimationName.REVIEW: "reviewing completed work, satisfied nod, thumbs up gesture",
    PetAnimationName.THINKING: "thinking deeply, hand to chin, small thoughtful head tilt",
    PetAnimationName.TYPING: "typing on a small laptop or keyboard, focused and rhythmic",
    PetAnimationName.READING: "reading a document or book carefully, eyes moving across the page",
    PetAnimationName.SEARCHING: "searching for information with a magnifying glass, curious expression",
    PetAnimationName.TOOL_USING: "using a tiny tool panel, focused hands-on work",
    PetAnimationName.CELEBRATE: "joyful success celebration, happy clap or victory pose",
    PetAnimationName.SLEEP: "sleeping peacefully, gentle breathing, small sleep bubble",
    PetAnimationName.SURPRISED: "brief surprised reaction, eyes wide, small hop",
    PetAnimationName.CONFUSED: "confused but friendly reaction, puzzled head scratch",
    PetAnimationName.PET: "enjoying a gentle head pat, happy and affectionate reaction",
}

BASIC_ROW_ORDER = [
    PetAnimationName.IDLE,
    PetAnimationName.RUNNING_RIGHT,
    PetAnimationName.RUNNING_LEFT,
    PetAnimationName.WAVING,
    PetAnimationName.JUMPING,
    PetAnimationName.FAILED,
    PetAnimationName.WAITING,
    PetAnimationName.RUNNING,
    PetAnimationName.REVIEW,
]

OFFICE_ACTIONS = [
    PetAnimationName.THINKING, PetAnimationName.TYPING, PetAnimationName.READING,
    PetAnimationName.SEARCHING, PetAnimationName.TOOL_USING, PetAnimationName.CELEBRATE,
    PetAnimationName.SLEEP,
]
INTERACTIVE_ACTIONS = [PetAnimationName.SURPRISED, PetAnimationName.CONFUSED, PetAnimationName.PET]
ACTION_PACKS = {
    "basic": BASIC_ROW_ORDER,
    "office": [*BASIC_ROW_ORDER, *OFFICE_ACTIONS],
    "interactive": [*BASIC_ROW_ORDER, *OFFICE_ACTIONS, *INTERACTIVE_ACTIONS],
}


def resolve_action_pack(action_pack: str) -> list[PetAnimationName]:
    """Return a safe ordered action list for a requested generation pack."""
    return ACTION_PACKS.get(action_pack, ACTION_PACKS["basic"])


# ── Image encoding helpers ────────────────────────────────────────────────

def _encode_data_url(image_path: str) -> str:
    """Read an image file and return a ``data:`` URL suitable for multimodal
    API requests."""
    import base64 as _b64
    import mimetypes

    mt = mimetypes.guess_type(image_path)[0] or "image/png"
    with open(image_path, "rb") as f:
        img_b64 = _b64.b64encode(f.read()).decode("ascii")
    return f"data:{mt};base64,{img_b64}"


# ── In-memory progress tracking ──────────────────────────────────────────
# Maps pet_id → progress dict. Consumed by the SSE endpoint in pets.py.
_generation_jobs: dict[str, dict[str, Any]] = {}


def get_generation_progress(pet_id: str) -> dict[str, Any] | None:
    """Return the current progress snapshot for a generation job."""
    return _generation_jobs.get(pet_id)


def get_all_active_jobs() -> list[dict[str, Any]]:
    """Return all in-progress generation jobs (for reconnecting SSE clients)."""
    import copy

    return [
        {
            "pet_id": pet_id,
            "step": job.get("step", 0),
            "total_steps": job.get("total_steps", 0),
            "step_name": job.get("step_name", ""),
            "step_label": job.get("step_label", ""),
            "status": job.get("status", "running"),
            "prompt": job.get("prompt", ""),
            "style": job.get("style", ""),
            "action_pack": job.get("action_pack", "basic"),
            "updated_at": job.get("updated_at", 0),
        }
        for pet_id, job in _generation_jobs.items()
        if job.get("status") not in ("done", "error")
    ]


def _set_progress(pet_id: str, **kwargs: Any) -> None:
    job = _generation_jobs.setdefault(pet_id, {})
    job.update(kwargs)
    job["updated_at"] = time.time()


def _clear_progress(pet_id: str) -> None:
    """Remove the progress entry (called after completion or error)."""
    _generation_jobs.pop(pet_id, None)


class PetGenerationService:
    """Generate Codex-compatible pet packages from text prompts."""

    def __init__(self, store: PetStore | None = None) -> None:
        self.store = store or PetStore()

    async def generate_from_prompt(
        self,
        pet_id: str,
        prompt: str,
        *,
        style: str = "pixel",
        user_id: int | None = None,
        reference_image_path: str | None = None,
        preserve_reference_style: bool = False,
        action_pack: str = "basic",
    ) -> None:
        """Full generation pipeline with live progress tracking.

        If *reference_image_path* is provided, the image is loaded and used as
        the base character design instead of generating one from scratch.
        """
        row_order = resolve_action_pack(action_pack)
        total_steps = 2 + len(row_order) + 2  # base + rows + compose + save
        _set_progress(
            pet_id,
            status="running",
            step=0,
            total_steps=total_steps,
            step_name="initializing",
            step_label="准备中…",
            prompt=prompt,
            style=style,
            action_pack=action_pack,
            started_at=time.time(),
        )
        logger.info("Pet generation started: id=%s prompt=%r style=%s", pet_id, prompt[:100], style)

        try:
            # Step 0: Resolve provider.
            _set_progress(pet_id, step_name="provider", step_label="查找图像生成服务…")
            provider_info = await self._resolve_provider()
            if not provider_info:
                logger.error("No image-capable provider found for pet generation")
                _set_progress(
                    pet_id, status="error", step_name="provider",
                    step_label="未找到图像生成服务，请配置 OpenAI 或 ChatGPT 提供商",
                    error="No image generation provider available",
                )
                await self._write_error_package(pet_id, prompt, "No image generation provider available")
                await asyncio.sleep(30)  # Keep error visible for 30s
                _clear_progress(pet_id)
                return

            # Step 1: Obtain base reference image (uploaded or generated).
            ref_visual_desc = ""
            if reference_image_path:
                _set_progress(pet_id, step=1, step_name="base", step_label="加载参考照片…")
                try:
                    base_image = Image.open(reference_image_path).convert("RGBA")
                    logger.info("Pet %s: using uploaded reference %s (%dx%d)",
                                pet_id, reference_image_path, base_image.width, base_image.height)
                    ref_visual_desc = self._extract_visual_description(base_image)
                    logger.info("Pet %s: reference visual desc: %s", pet_id, ref_visual_desc[:200])
                    _set_progress(pet_id, step_label="参考照片加载完成 ✓")
                except Exception as e:
                    logger.warning("Pet %s: failed to load reference, falling back to generation: %s", pet_id, e)
                    _set_progress(pet_id, step=1, step_name="base", step_label="生成角色参考图…")
                    base_image = await self._generate_base(pet_id, prompt, style, provider_info)
            else:
                _set_progress(pet_id, step=1, step_name="base", step_label="生成角色参考图…")
                base_image = await self._generate_base(pet_id, prompt, style, provider_info)
            if not base_image:
                logger.error("Base image generation failed for pet %s", pet_id)
                _set_progress(
                    pet_id, status="error", step_name="base",
                    step_label="角色参考图生成失败",
                    error="Base image generation failed",
                )
                await self._write_error_package(pet_id, prompt, "Base image generation failed")
                await asyncio.sleep(30)
                _clear_progress(pet_id)
                return

            logger.info("Pet %s: base image generated (%dx%d)", pet_id, base_image.width, base_image.height)
            self.store.save_original_image(pet_id, "base.png", base_image)
            _set_progress(pet_id, step_label="角色参考图生成完成 ✓")

            # Step 2-10: Generate row strips.
            strips: dict[PetAnimationName, list[Image.Image]] = {}
            row_labels = {
                PetAnimationName.IDLE: "待机动画",
                PetAnimationName.RUNNING_RIGHT: "向右跑动画",
                PetAnimationName.RUNNING_LEFT: "向左跑动画",
                PetAnimationName.WAVING: "挥手动画",
                PetAnimationName.JUMPING: "跳跃动画",
                PetAnimationName.FAILED: "失败动画",
                PetAnimationName.WAITING: "等待动画",
                PetAnimationName.RUNNING: "工作动画",
                PetAnimationName.REVIEW: "完成动画",
            }
            for i, row in enumerate(row_order):
                step_num = 2 + i
                label = row_labels.get(row, row.value)
                _set_progress(
                    pet_id, step=step_num, step_name=f"row_{row.value}",
                    step_label=f"生成{label}（{step_num - 1}/{total_steps - 2}）…",
                )

                n_frames = FRAME_COUNTS[row]
                try:
                    if row == PetAnimationName.IDLE:
                        frames = await self._generate_stable_idle_frames(
                            pet_id,
                            prompt,
                            style,
                            base_image,
                            provider_info,
                            preserve_reference_style=preserve_reference_style,
                        )
                        strips[row] = frames
                    elif row in {
                        PetAnimationName.RUNNING_RIGHT,
                        PetAnimationName.RUNNING_LEFT,
                    }:
                        # Wide running poses overlap in eight-frame strips.
                        # Generate two four-frame strips instead: this keeps each
                        # panel wide enough without making eight image requests.
                        frames = await self._generate_running_frame_batches(
                            pet_id, prompt, style, row, n_frames, base_image, provider_info,
                            reference_image_path=reference_image_path,
                            ref_visual_desc=ref_visual_desc,
                            preserve_reference_style=preserve_reference_style,
                        )
                        strips[row] = frames
                    else:
                        strip = await self._generate_row_strip(
                            pet_id, prompt, style, row, n_frames, base_image, provider_info,
                            reference_image_path=reference_image_path,
                            ref_visual_desc=ref_visual_desc,
                            preserve_reference_style=preserve_reference_style,
                        )
                        if strip:
                            self.store.save_original_image(pet_id, f"{row.value}.png", strip)
                            strips[row] = self._extract_frames(strip, n_frames, row_name=row)
                        else:
                            raise RuntimeError("Animation strip generation returned no image")
                    logger.info("Pet %s: row %s -> %d frames", pet_id, row.value, len(strips[row]))
                except Exception as e:
                    logger.warning("Pet %s: row %s generation failed: %s", pet_id, row.value, e)
                    fallback = Image.open(reference_image_path).convert("RGBA") if reference_image_path else base_image
                    strips[row] = [self._fit_to_cell(fallback)]

                await asyncio.sleep(0.5)

            # Step 11: Compose atlas.
            step_compose = 2 + len(row_order)
            _set_progress(
                pet_id, step=step_compose, step_name="compose",
                step_label="合成精灵图…",
            )
            atlas = self._compose_atlas(strips, row_order)
            logger.info("Pet %s: atlas composed %dx%d", pet_id, atlas.width, atlas.height)

            # Step 12: Save package.
            step_save = step_compose + 1
            _set_progress(
                pet_id, step=step_save, step_name="save",
                step_label="保存宠物包…",
            )
            config = PetConfig(
                id=pet_id,
                displayName=pet_id.replace("-", " ").title(),
                description=prompt,
                spritesheetPath="spritesheet.png",
                rows=len(row_order),
                action_pack=action_pack if action_pack in ACTION_PACKS else "basic",
                animations={
                    row.value: {
                        "row": index,
                        "frames": max(len(strips.get(row, [])), 1),
                        "frameDuration": 150,
                        "loop": row not in {
                            PetAnimationName.CELEBRATE,
                            PetAnimationName.SURPRISED,
                            PetAnimationName.PET,
                        },
                    }
                    for index, row in enumerate(row_order)
                },
                type="spritesheet",
            )
            config.frame_counts = {k: max(len(v), 1) for k, v in strips.items() if k in FRAME_COUNTS}

            self.store.write_config(pet_id, config.model_dump(mode="json"))
            spritesheet_path = self.store.spritesheet_path(pet_id, "spritesheet.png")
            atlas.save(spritesheet_path, "PNG")

            if user_id is not None:
                await self._persist_to_db(pet_id, config, user_id)

            logger.info("Pet generation complete: %s at %s", pet_id, spritesheet_path)
            _set_progress(
                pet_id, status="done", step=total_steps, step_name="done",
                step_label="生成完成！",
            )
            # Keep "done" state for 60s so the SSE client sees it.
            await asyncio.sleep(60)
            _clear_progress(pet_id)

        except Exception as e:
            logger.exception("Pet generation failed for %s: %s", pet_id, e)
            _set_progress(
                pet_id, status="error", step_name="exception",
                step_label=f"生成失败：{e}",
                error=str(e),
            )
            await self._write_error_package(pet_id, prompt, str(e))
            await asyncio.sleep(30)
            _clear_progress(pet_id)

    async def expand_action_pack(
        self,
        pet_id: str,
        action_pack: str,
        *,
        user_id: int,
    ) -> None:
        """Generate only the rows missing from an existing pet package."""
        requested_rows = resolve_action_pack(action_pack)
        config = PetConfig.model_validate(self.store.read_config(pet_id))
        existing = set(config.animations)
        if not config.animations:
            existing = {row.value for row in BASIC_ROW_ORDER}
            config.animations = {
                row.value: {"row": index, "frames": config.frame_counts.get(row, 1),
                            "frameDuration": config.frame_rates.get(row, 150), "loop": True}
                for index, row in enumerate(BASIC_ROW_ORDER)
            }
        missing = [row for row in requested_rows if row.value not in existing]
        if not missing:
            _set_progress(pet_id, status="done", step=1, total_steps=1, step_name="done", step_label="动作包已完整")
            await asyncio.sleep(5)
            _clear_progress(pet_id)
            return

        _set_progress(
            pet_id, status="running", step=0, total_steps=len(missing) + 2,
            step_name="initializing", step_label="准备补充动作…", action_pack=action_pack,
        )
        try:
            provider_info = await self._resolve_provider()
            if not provider_info:
                raise RuntimeError("No image generation provider available")
            atlas_path = self.store.spritesheet_path(pet_id, config.spritesheetPath)
            atlas = Image.open(atlas_path).convert("RGBA")
            base_image = self.store.original_path(pet_id, "base.png")
            reference = str(base_image) if base_image.exists() else None
            base = Image.open(base_image).convert("RGBA") if base_image.exists() else atlas.crop((0, 0, CELL_W, CELL_H))
            strips: dict[PetAnimationName, list[Image.Image]] = {}
            for index, row in enumerate(missing, start=1):
                _set_progress(pet_id, step=index, step_name=f"row_{row.value}", step_label=f"补充 {row.value} 动作…")
                strip = await self._generate_row_strip(
                    pet_id, config.description, "pixel", row, FRAME_COUNTS[row], base, provider_info,
                    reference_image_path=reference,
                )
                strips[row] = self._extract_frames(strip, FRAME_COUNTS[row], row_name=row) if strip else [self._fit_to_cell(base)]
                await asyncio.sleep(0.5)

            expanded = Image.new("RGBA", (ATLAS_W, CELL_H * len(requested_rows)), (0, 0, 0, 0))
            expanded.paste(atlas, (0, 0), atlas)
            for row_index, row in enumerate(requested_rows):
                if row not in strips:
                    continue
                for col_index, frame in enumerate(strips[row]):
                    if col_index < COLS:
                        expanded.paste(frame, (col_index * CELL_W, row_index * CELL_H), frame)
                config.animations[row.value] = {
                    "row": row_index, "frames": len(strips[row]), "frameDuration": 150,
                    "loop": row not in {PetAnimationName.CELEBRATE, PetAnimationName.SURPRISED, PetAnimationName.PET},
                }
            config.rows = len(requested_rows)
            config.action_pack = action_pack
            _set_progress(pet_id, step=len(missing) + 1, step_name="save", step_label="保存扩展动作…")
            expanded.save(atlas_path, "PNG")
            self.store.write_config(pet_id, config.model_dump(mode="json"))
            await self._persist_to_db(pet_id, config, user_id)
            _set_progress(pet_id, status="done", step=len(missing) + 2, step_name="done", step_label="动作包补充完成！")
            await asyncio.sleep(60)
            _clear_progress(pet_id)
        except Exception as exc:
            logger.exception("Pet action-pack expansion failed for %s", pet_id)
            _set_progress(pet_id, status="error", step_name="exception", step_label=f"补充失败：{exc}", error=str(exc))
            await asyncio.sleep(30)
            _clear_progress(pet_id)

    # ── Provider resolution ──────────────────────────────────────────

    async def _resolve_provider(self) -> Any:
        """Find an image-capable provider (chatgpt or openai)."""
        from crabagent.core.provider_store import get_default_provider, list_providers

        _IMAGE_CAPABLE = {"chatgpt", "openai"}

        default = await get_default_provider()
        if default and default.provider_type in _IMAGE_CAPABLE:
            return default

        all_providers = await list_providers()
        for p in all_providers:
            if p.provider_type in _IMAGE_CAPABLE and p.enabled:
                return p

        return None

    def _resolve_model_and_kwargs(self, provider_info: Any) -> tuple[str, dict[str, str]]:
        if provider_info.provider_type == "chatgpt":
            return "chatgpt/image-2", {}

        kwargs: dict[str, str] = {}
        if provider_info.api_key:
            kwargs["api_key"] = provider_info.api_key
        if provider_info.base_url:
            kwargs["api_base"] = provider_info.base_url
        return "gpt-image-1", kwargs

    def _setup_litellm_provider(self, provider_info: Any) -> None:
        import litellm

        if provider_info.provider_type == "openai":
            if provider_info.api_key:
                litellm.api_key = provider_info.api_key
            if provider_info.base_url:
                litellm.api_base = provider_info.base_url

    # ── Image generation ─────────────────────────────────────────────

    @staticmethod
    def _extract_visual_description(image: Image.Image) -> str:
        """Extract a compact visual description from a reference image using PIL.

        Since ChatGPT subscription can't do vision analysis through the codex
        API, and litellm's image_edit doesn't support the chatgpt provider,
        we extract dominant colours and basic features with PIL and embed them
        into the text prompt so the image generator has at least some anchor.
        """
        from collections import Counter

        img = image.convert("RGB")
        if max(img.size) > 256:
            ratio = 256 / max(img.size)
            img = img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))))

        pixels = list(img.getdata())
        if not pixels:
            return "Reference image contains no visible pixels"

        # Dominant colours via simple quantisation to 4×4×4 = 64 buckets.
        # Keep this dependency-free: packaged builds do not include NumPy.
        codes = [r // 64 * 16 + g // 64 * 4 + b // 64 for r, g, b in pixels]
        counts = Counter(codes)
        sorted_buckets = counts.most_common(4)

        def _bucket_to_hex(code: int) -> tuple[str, str]:
            r = (code // 16) * 64 + 32
            g = ((code % 16) // 4) * 64 + 32
            b = (code % 4) * 64 + 32
            hex_code = f"#{r:02X}{g:02X}{b:02X}"
            # Rough colour name
            if r > 200 and g > 200 and b > 200:
                name = "white/cream"
            elif r < 60 and g < 60 and b < 60:
                name = "black/dark"
            elif r > g + 40 and r > b + 40:
                name = "red/orange" if g < 150 else "pink"
            elif g > r + 40 and g > b + 40:
                name = "green"
            elif b > r + 40 and b > g + 40:
                name = "blue"
            elif r > 180 and g > 180 and b < 120:
                name = "yellow/gold"
            elif r > 150 and g < 120 and b < 120:
                name = "brown/tan"
            elif r > 120 and g > 100 and b > 100:
                name = "grey"
            else:
                name = "muted"
            return hex_code, name

        top_colours = []
        for code, count in sorted_buckets:
            pct = count / len(codes) * 100
            if pct < 3:
                break
            hex_code, name = _bucket_to_hex(code)
            top_colours.append(f"{name} ({hex_code}, {pct:.0f}%)")

        # Overall brightness and warmth
        brightness = sum(sum(pixel) for pixel in pixels) / (len(pixels) * 3)
        is_warm = sum(pixel[0] for pixel in pixels) > sum(pixel[2] for pixel in pixels)

        parts = [
            f"Dominant colours: {', '.join(top_colours)}",
            f"Overall tone: {'warm' if is_warm else 'cool'}, brightness {'bright' if brightness > 160 else 'medium' if brightness > 90 else 'dark'}",
        ]

        # Aspect ratio hint
        w, h = image.size
        parts.append(f"Image aspect ratio: {w}:{h}")

        return "; ".join(parts)

    async def _generate_base(
        self,
        pet_id: str,
        prompt: str,
        style: str,
        provider_info: Any,
    ) -> Image.Image | None:
        import litellm

        model, kwargs = self._resolve_model_and_kwargs(provider_info)
        self._setup_litellm_provider(provider_info)

        style_desc = self._style_descriptor(style)
        full_prompt = (
            f"{style_desc} character design sheet. {prompt}. "
            f"Single character, full body, centered, facing forward, simple pose. "
            f"Clean solid green background (#00FF00) for chroma key removal. "
            f"No text, no borders, no shadows on background."
        )

        try:
            resp = await litellm.aimage_generation(
                model=model,
                prompt=full_prompt,
                size="1024x1024",
                n=1,
                quality="high" if provider_info.provider_type == "openai" else "auto",
                timeout=120,
                **kwargs,
            )
            return self._extract_image_from_response(resp)
        except Exception as e:
            logger.error("Base image generation failed: %s", e)
            return None

    async def _generate_stable_idle_frames(
        self,
        pet_id: str,
        prompt: str,
        style: str,
        base_image: Image.Image,
        provider_info: Any,
        *,
        preserve_reference_style: bool = False,
    ) -> list[Image.Image]:
        """Build idle from a canonical pose plus one model-generated blink.

        Generating six independent "idle" panels makes the whole character
        drift even when the prompt asks for a locked camera. Instead, make one
        canonical pose and a single image-to-image blink from that exact pose.
        The rest of the loop deliberately holds the canonical frame, so the
        pet remains planted while still feeling alive.
        """
        canonical_source = self.store.original_path(pet_id, "idle-base.png")
        self.store.save_original_image(pet_id, "idle-base.png", base_image)
        canonical = await self._generate_row_strip(
            pet_id,
            prompt,
            style,
            PetAnimationName.IDLE,
            1,
            base_image,
            provider_info,
            reference_image_path=str(canonical_source),
            preserve_reference_style=preserve_reference_style,
            frame_index=0,
            total_frames=1,
        )
        if not canonical:
            raise RuntimeError("Canonical idle generation returned no image")
        self.store.save_original_image(pet_id, "idle-canonical.png", canonical)
        canonical_frame = self._extract_frames(
            canonical,
            1,
            row_name=PetAnimationName.IDLE,
        )[0]

        model, kwargs = self._resolve_model_and_kwargs(provider_info)
        self._setup_litellm_provider(provider_info)
        blink_prompt = (
            "Use the supplied desktop-pet sprite as a strict visual reference. "
            "Create one matching full-body sprite with exactly one natural, soft closed-eye blink. "
            "Keep the pose, paws, body silhouette, head position, outfit, mouth, camera framing, "
            "scale, lighting, and solid green (#00FF00) background unchanged. "
            "The eyelids must use the character's own fur and rendering style; do not draw graphic "
            "lines over the eyes. No text, panels, extra objects, duplicate character, crop, or drift."
        )
        blink = await self._image_edit(
            model,
            blink_prompt,
            str(self.store.original_path(pet_id, "idle-canonical.png")),
            size="1024x1024",
            kwargs=kwargs,
            provider_type=provider_info.provider_type,
        )
        if not blink:
            raise RuntimeError("Natural blink generation returned no image")
        self.store.save_original_image(pet_id, "idle-blink.png", blink)
        blink_frame = self._extract_frames(blink, 1, row_name=PetAnimationName.IDLE)[0]

        # One blink in a six-frame loop; the holds make it read as a calm idle.
        frames = [
            canonical_frame,
            canonical_frame.copy(),
            blink_frame,
            canonical_frame.copy(),
            canonical_frame.copy(),
            canonical_frame.copy(),
        ]
        return self._align_frames(frames, max_shift=4)

    async def _generate_running_frame_batches(
        self,
        pet_id: str,
        prompt: str,
        style: str,
        row: PetAnimationName,
        n_frames: int,
        base_image: Image.Image,
        provider_info: Any,
        reference_image_path: str | None = None,
        ref_visual_desc: str = "",
        preserve_reference_style: bool = False,
    ) -> list[Image.Image]:
        """Generate running animation as two short strips to prevent overlap."""
        frames: list[Image.Image] = []
        batch_size = 4
        for start in range(0, n_frames, batch_size):
            count = min(batch_size, n_frames - start)
            strip = await self._generate_row_strip(
                pet_id,
                prompt,
                style,
                row,
                count,
                base_image,
                provider_info,
                reference_image_path=reference_image_path,
                ref_visual_desc=ref_visual_desc,
                preserve_reference_style=preserve_reference_style,
                frame_index=start,
                total_frames=n_frames,
            )
            if not strip:
                raise RuntimeError(f"Running frame batch {start + 1}/{n_frames} generation returned no image")
            batch = start // batch_size + 1
            self.store.save_original_image(pet_id, f"{row.value}-batch-{batch}.png", strip)
            frames.extend(self._extract_frames(strip, count, row_name=row))
        return frames

    async def _generate_row_strip(
        self,
        pet_id: str,
        prompt: str,
        style: str,
        row: PetAnimationName,
        n_frames: int,
        base_image: Image.Image,
        provider_info: Any,
        reference_image_path: str | None = None,
        ref_visual_desc: str = "",
        preserve_reference_style: bool = False,
        frame_index: int | None = None,
        total_frames: int | None = None,
    ) -> Image.Image | None:
        """Generate a strip image containing multiple animation frames.

        When a reference photo is available, it is passed to the image edit
        API (gpt-image-1) or described in the prompt to maintain consistency.

        A layout guide is generated for multi-frame rows and passed to the
        image model as an invisible construction reference.
        """
        import litellm

        model, kwargs = self._resolve_model_and_kwargs(provider_info)
        self._setup_litellm_provider(provider_info)

        # Generate layout guide for multi-frame rows
        layout_guide_path: str | None = None
        if n_frames > 1:
            layout_guide_path = self._generate_layout_guide(pet_id, row, n_frames)

        style_desc = self._style_descriptor(style)
        if reference_image_path and preserve_reference_style:
            style_desc = (
                "preserve the reference image's original visual medium, rendering, "
                "texture, lighting, and color treatment; do not stylize it"
            )
        anim_desc = ANIMATION_PROMPTS.get(row, "idle pose")

        # Build the prompt. If a reference photo was uploaded, add explicit
        # instructions to match the photo's appearance.
        ref_instruction = ""
        if reference_image_path:
            ref_instruction = (
                " The character MUST look exactly like the provided reference image: "
                "same species, colors, markings, proportions, and accessories. "
                "Do not change the character's identity."
            )
            if preserve_reference_style:
                ref_instruction += (
                    " Preserve the reference image's original visual style exactly; "
                    "do not apply any requested art style."
                )
            # For providers that can't see the image (ChatGPT subscription),
            # embed the extracted visual description so the generator has
            # at least some colour/tone anchor from the reference.
            if ref_visual_desc:
                ref_instruction += (
                    f" Reference image analysis: {ref_visual_desc}."
                    " Match these colours and tones exactly."
                )

        is_single_frame = n_frames == 1 and frame_index is not None and total_frames is not None
        layout_instruction = (
            f"Show one full-body animation frame ({frame_index + 1}/{total_frames}) of: {anim_desc}. "
            "Use a fixed camera viewport with the entire character, props, and ground fully visible. "
            "Do not create a strip, panels, duplicated characters, or cropped edges. "
            if is_single_frame
            else (
                f"Show exactly {n_frames} consecutive frames of: {anim_desc}. "
                f"These are frames {frame_index + 1}-{frame_index + n_frames} of {total_frames}. "
                f"Arrange exactly {n_frames} equal-width, fully isolated panels left to right in one horizontal row. "
                "Leave at least 12% solid-green empty space on both sides of every panel. "
                if frame_index is not None and total_frames is not None
                else (
                    f"Show exactly {n_frames} consecutive frames of: {anim_desc}. "
                    f"Arrange exactly {n_frames} equal-width, fully isolated panels left to right in one horizontal row. "
                )
            )
        )
        asset_kind = "single animation frame" if is_single_frame else "animation sprite strip"
        full_prompt = (
            f"{style_desc} {asset_kind}. Same character as: {prompt}."
            f"{ref_instruction} "
            f"{layout_instruction}"
            f"CRITICAL: every panel is a fixed camera viewport. Keep the character, "
            f"props, desk, and ground anchored at the exact same horizontal position "
            f"and scale in every panel; only body parts needed for the animation may move. "
            f"Do not pan the camera, translate the composition, make the character walk "
            f"across panels, crop any edge, or let objects cross between panels. "
            f"Every character pixel, prop, desk, and ground must be fully visible inside its own panel; "
            f"leave clear solid-green space around the complete subject, especially at the left and right edges. "
            f"Consistent character design: same colors, proportions, and style across all frames. "
            f"Clean solid green background (#00FF00) for chroma key removal. "
            f"No text, no borders, no panel separators."
        )
        if n_frames > 1:
            full_prompt += (
                f" LAYOUT: exactly {n_frames} equal-width panels in one horizontal row. "
                f"Each panel is {CELL_W}x{CELL_H}px with clean green separation between them. "
                "The panel structure must match the provided layout guide image."
            )
        if row == PetAnimationName.IDLE:
            full_prompt += (
                " IDLE STABILITY RULE: use a locked-off camera and a planted base pose. "
                "The silhouette's horizontal center, feet, ground contact, scale, and framing "
                "must be identical in every frame. Do not lean, sway side-to-side, or shift weight; "
                "only a tiny blink or a very subtle internal facial change is allowed."
            )

        try:
            # When a reference image is available, ALWAYS use the image edit API
            # so the model can actually see the reference.  This works for both
            # OpenAI API (gpt-image-1 via litellm.aimage_edit) and ChatGPT
            # subscription (via codex/responses with image_generation tool).
            if reference_image_path:
                # Image edits occasionally fail transiently (especially the
                # ChatGPT streaming endpoint). A text-only fallback cannot
                # preserve the uploaded pet identity, so retry the edit and
                # never silently replace it with an unrelated generated pet.
                for attempt in range(1, 4):
                    try:
                        resp = await self._image_edit(
                            model, full_prompt, reference_image_path,
                            size="1536x1024", kwargs=kwargs,
                            provider_type=provider_info.provider_type,
                            layout_guide_path=layout_guide_path,
                        )
                        if resp:
                            return resp
                        logger.warning(
                            "Image edit returned nothing for %s (attempt %d/3)",
                            row.value,
                            attempt,
                        )
                    except Exception as e:
                        logger.warning(
                            "Image edit failed for %s (attempt %d/3): %r",
                            row.value,
                            attempt,
                            e,
                        )
                    if attempt < 3:
                        await asyncio.sleep(attempt)

                logger.error(
                    "Image edit exhausted retries for %s; preserving the reference instead of generating a different pet",
                    row.value,
                )
                return None

            resp = await litellm.aimage_generation(
                model=model,
                prompt=full_prompt,
                size="1536x1024",
                n=1,
                quality="standard",
                timeout=120,
                **kwargs,
            )
            return self._extract_image_from_response(resp)
        except Exception as e:
            logger.warning("Row strip generation failed for %s: %s", row.value, e)
            return None

    async def _image_edit(
        self,
        model: str,
        prompt: str,
        image_path: str,
        *,
        size: str = "1536x1024",
        kwargs: dict[str, Any] | None = None,
        provider_type: str = "",
        layout_guide_path: str | None = None,
    ) -> Image.Image | None:
        """Generate an image that references an existing image.

        For OpenAI API providers this uses the standard ``images/edits``
        endpoint via ``litellm.aimage_edit``.

        For ChatGPT subscription providers (where litellm does not support
        image_edit) this sends a multimodal request to the Codex responses
        endpoint (``/backend-api/codex/responses``) with the reference image
        embedded as ``input_image`` content and the ``image_generation`` tool
        enabled.  This is the same approach used by Codex CLI image skills.

        When *layout_guide_path* is provided it is forwarded as an additional
        reference image that shows the model the expected frame grid.
        """

        # ── ChatGPT subscription: use codex/responses with image_generation tool ──
        if provider_type == "chatgpt":
            return await self._chatgpt_image_edit(
                prompt, image_path, layout_guide_path=layout_guide_path,
            )

        # ── OpenAI API: use litellm.aimage_edit ──
        import litellm

        with open(image_path, "rb") as f:
            image_data = f.read()

        try:
            resp = await litellm.aimage_edit(
                model=model,
                image=image_data,
                prompt=prompt,
                size=size,
                n=1,
                timeout=120,
                **(kwargs or {}),
            )
            return self._extract_image_from_response(resp)
        except Exception as e:
            logger.warning("Image edit API call failed: %s", e)
            return None

    async def _chatgpt_image_edit(
        self,
        prompt: str,
        image_path: str,
        *,
        layout_guide_path: str | None = None,
    ) -> Image.Image | None:
        """Generate image from a reference via ChatGPT Codex responses API.

        Sends the reference image as multimodal ``input_image`` content to
        ``/backend-api/codex/responses`` with the ``image_generation`` tool.
        The model sees the reference and generates a new image based on it.

        When *layout_guide_path* is provided, it is attached as a second
        ``input_image`` in the same message so the model can follow the
        expected frame count, spacing, and padding from the visual guide."""
        import base64 as _b64
        import mimetypes
        import re

        from crabagent.serve.api.chatgpt_auth import get_chatgpt_access_token

        CHATGPT_API_BASE = "https://chatgpt.com/backend-api/codex"

        try:
            access_token = await get_chatgpt_access_token()
        except Exception as e:
            logger.warning("ChatGPT auth failed for image edit: %s", e)
            return None

        # Build the content array with the character reference
        content: list[dict] = [
            {
                "type": "input_text",
                "text": (
                    "Use the image generation tool to create a new image "
                    "based on the reference image(s). "
                    "Preserve the main character identity, colors, and style. "
                    "Request: " + prompt
                ),
            },
            {
                "type": "input_image",
                "image_url": _encode_data_url(image_path),
            },
        ]

        # Attach the layout guide as a second input image
        if layout_guide_path:
            content.append({
                "type": "input_text",
                "text": (
                    "The following image is an invisible layout guide showing "
                    f"the exact frame grid you need to draw. Follow its cell "
                    "count, spacing, and centering. Do NOT include visible "
                    "borders, labels, or guide colors in the output."
                ),
            })
            content.append({
                "type": "input_image",
                "image_url": _encode_data_url(layout_guide_path),
            })

        payload = {
            "model": "gpt-5.4",
            "instructions": "You are a helpful assistant. Use tools when available.",
            "input": [{"role": "user", "content": content}],
            "store": False,
            "tools": [{"type": "image_generation"}],
            "reasoning": {"effort": "low"},
            "include": [],
            "tool_choice": "auto",
            "parallel_tool_calls": True,
            "stream": True,
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "codex_cli_rs/0.0.0 (Darwin 24.0; arm64) xterm-256color",
            "originator": "codex_cli_rs",
        }

        try:
            async with httpx.AsyncClient(timeout=240) as client:
                async with client.stream(
                    "POST",
                    f"{CHATGPT_API_BASE}/responses",
                    headers=headers,
                    json=payload,
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        logger.warning(
                            "ChatGPT image edit HTTP %d: %s",
                            resp.status_code,
                            body[:500],
                        )
                        return None

                    raw = b""
                    async for chunk in resp.aiter_bytes():
                        raw += chunk

            text = raw.decode("utf-8", errors="replace")
            matches = re.findall(r"(iVBOR[A-Za-z0-9+/=]{1000,})", text)
            if not matches:
                logger.warning("ChatGPT image edit: no image data in response")
                return None

            img_bytes = _b64.b64decode(matches[0])
            return Image.open(io.BytesIO(img_bytes)).convert("RGBA")

        except Exception as e:
            logger.warning("ChatGPT image edit failed: %s", e)
            return None

    # ── Image processing ─────────────────────────────────────────────

    def _extract_image_from_response(self, resp: Any) -> Image.Image | None:
        data = resp.get("data") if isinstance(resp, dict) else getattr(resp, "data", None)
        if not data or not isinstance(data, list) or len(data) == 0:
            return None

        item = data[0]
        if not isinstance(item, dict):
            item = vars(item) if hasattr(item, "__dict__") else {}

        b64 = item.get("b64_json", "")
        if b64:
            if "," in b64 and b64.startswith("data:"):
                b64 = b64.split(",", 1)[1]
            raw = base64.b64decode(b64)
            return Image.open(io.BytesIO(raw)).convert("RGBA")

        url = item.get("url", "")
        if url:
            return self._download_image(url)

        return None

    def _download_image(self, url: str) -> Image.Image | None:
        import ssl

        import httpx

        try:
            ssl_ctx = ssl.create_default_context()
            with httpx.Client(verify=ssl_ctx, timeout=60.0, follow_redirects=True) as client:
                resp = client.get(url)
                resp.raise_for_status()
                return Image.open(io.BytesIO(resp.content)).convert("RGBA")
        except Exception as e:
            logger.warning("Failed to download image: %s", e)
            return None

    # Rows whose scene must stay anchored. The animation may change an arm,
    # face, or tail, but the character's planted base (and desk, when present)
    # must never drift through the transparent window.
    _STATIONARY_ROWS = frozenset({
        PetAnimationName.IDLE,
        PetAnimationName.WAVING,
        PetAnimationName.FAILED,
        PetAnimationName.WAITING,
        PetAnimationName.RUNNING,   # "working at desk" — character stays put
        PetAnimationName.REVIEW,
        PetAnimationName.THINKING,
        PetAnimationName.TYPING,
        PetAnimationName.READING,
        PetAnimationName.SEARCHING,
        PetAnimationName.TOOL_USING,
        PetAnimationName.CELEBRATE,
        PetAnimationName.SLEEP,
    })

    @staticmethod
    def _align_frames(frames: list[Image.Image], max_shift: int = 18) -> list[Image.Image]:
        """Register anchored frames in both axes using alpha-mask overlap.

        AI sprite strips often drift by one to several pixels vertically as
        well as horizontally. Bounding boxes cannot distinguish that camera
        movement from a raised paw or a wagging tail. Searching the small 2-D
        translation space on alpha masks locks the shared silhouette/scene in
        place while keeping the local pose change intact.
        """
        if len(frames) <= 1:
            return frames

        reference = frames[0].getchannel("A").point(lambda value: 255 if value > 40 else 0)
        if not reference.getbbox():
            return frames

        def _overlap_score(mask: Image.Image, dx: int, dy: int) -> int:
            """Return opaque-pixel overlap after moving *mask* by ``dx, dy``."""
            width, height = mask.size
            left = max(0, dx)
            top = max(0, dy)
            right = min(width, width + dx)
            bottom = min(height, height + dy)
            if left >= right or top >= bottom:
                return 0
            ref_crop = reference.crop((left, top, right, bottom))
            mask_crop = mask.crop((left - dx, top - dy, right - dx, bottom - dy))
            # Both masks are binary, so bin 255 is the opaque-pixel overlap.
            return ImageChops.multiply(ref_crop, mask_crop).histogram()[255]

        aligned = [frames[0]]
        for frame in frames[1:]:
            mask = frame.getchannel("A").point(lambda value: 255 if value > 40 else 0)
            if not mask.getbbox():
                aligned.append(frame)
                continue

            # Prefer the smallest correction when multiple placements match.
            dx, dy = max(
                (
                    (candidate_x, candidate_y)
                    for candidate_y in range(-max_shift, max_shift + 1)
                    for candidate_x in range(-max_shift, max_shift + 1)
                ),
                key=lambda candidate: (
                    _overlap_score(mask, candidate[0], candidate[1]),
                    -(abs(candidate[0]) + abs(candidate[1])),
                ),
            )
            if dx == 0 and dy == 0:
                aligned.append(frame)
                continue

            canvas = Image.new("RGBA", frame.size, (0, 0, 0, 0))
            # Use paste rather than alpha_composite so later atlas writes can
            # replace an entire transparent cell without leaving old pixels.
            canvas.paste(frame, (dx, dy))
            aligned.append(canvas)

        return aligned

    def _extract_frames(self, strip: Image.Image, n_frames: int, row_name: PetAnimationName | None = None) -> list[Image.Image]:
        """Extract frames from a horizontal strip using a three-layer strategy.

        Layer 1 — Connected components: find sprite blobs in the full strip
        after chroma removal, group them into N frames by horizontal position.
        This is robust against uneven spacing, overlapping poses, and varying
        sprite sizes.

        Layer 2 — Stable slots: when components can't separate N frames
        (e.g. sprites are fused together), fall back to equal-width splitting
        with a shared viewport so all frames get identical dimensions. This
        prevents size popping without hiding real layout problems.

        Layer 3 — Cross-correlation alignment: for stationary rows (idle,
        working, …) register every frame against frame 0 in both axes to
        cancel residual camera/composition drift. This is the existing
        CrabAgent alignment pass, applied after extraction.
        """
        # Layer 1 input: remove green from the *entire* strip first
        no_bg_strip = self._remove_green_background(strip)

        # Try connected-components extraction first
        cell_frames = self._extract_component_frames(no_bg_strip, n_frames)

        # Layer 2: stable-slots fallback
        if cell_frames is None:
            logger.debug(
                "Component extraction failed for %s (%d frames), falling back to stable-slots",
                row_name, n_frames,
            )
            cell_frames = self._extract_stable_slot_frames(no_bg_strip, n_frames)

        # Pad to n_frames if extraction returned fewer (edge cases)
        while len(cell_frames) < n_frames:
            cell_frames.append(Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0)))

        # Layer 3: cross-correlation alignment for stationary rows
        if row_name and row_name in self._STATIONARY_ROWS:
            cell_frames = self._align_frames(cell_frames)

        return cell_frames

    # ── Connected-component extraction (Layer 1) ─────────────────────

    @staticmethod
    def _find_connected_components(image: Image.Image) -> list[dict[str, Any]]:
        """Find all connected components in an RGBA image using the alpha channel.

        Uses 4-connectivity flood fill. Returns components sorted by area
        descending, each with pixel indices, bounding box, and center_x.
        """
        alpha = image.getchannel("A")
        width, height = image.size
        data = alpha.tobytes()
        visited = bytearray(width * height)
        components: list[dict[str, Any]] = []

        for seed in range(len(data)):
            if data[seed] <= 16 or visited[seed]:
                continue

            stack = [seed]
            visited[seed] = 1
            pixels: list[int] = []
            min_x, min_y = width, height
            max_x, max_y = 0, 0

            while stack:
                current = stack.pop()
                pixels.append(current)
                x = current % width
                y = current // width
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y

                if x > 0:
                    n = current - 1
                    if not visited[n] and data[n] > 16:
                        visited[n] = 1
                        stack.append(n)
                if x + 1 < width:
                    n = current + 1
                    if not visited[n] and data[n] > 16:
                        visited[n] = 1
                        stack.append(n)
                if y > 0:
                    n = current - width
                    if not visited[n] and data[n] > 16:
                        visited[n] = 1
                        stack.append(n)
                if y + 1 < height:
                    n = current + width
                    if not visited[n] and data[n] > 16:
                        visited[n] = 1
                        stack.append(n)

            components.append({
                "pixels": pixels,
                "area": len(pixels),
                "bbox": (min_x, min_y, max_x + 1, max_y + 1),
                "center_x": (min_x + max_x + 1) / 2,
            })

        components.sort(key=lambda c: c["area"], reverse=True)
        return components

    @staticmethod
    def _group_components_into_frames(
        components: list[dict[str, Any]], n_frames: int,
    ) -> list[list[dict[str, Any]]] | None:
        """Group connected components into N frames by horizontal position.

        Selects the N largest components as seeds (threshold: ≥20% of the
        largest), sorts them left-to-right, then assigns each small fragment
        to its nearest seed by center_x.

        Returns None when fewer than n_frames components exist.
        """
        if not components:
            return None

        largest_area = components[0]["area"]
        seed_threshold = max(120, largest_area * 0.20)
        seeds = [c for c in components if c["area"] >= seed_threshold]

        if len(seeds) < n_frames:
            seeds = components[:n_frames]

        if len(seeds) < n_frames:
            return None

        seeds = sorted(seeds[:n_frames], key=lambda c: c["center_x"])
        seed_ids = {id(s) for s in seeds}
        groups: list[list[dict[str, Any]]] = [[seed] for seed in seeds]
        noise_threshold = max(12, largest_area * 0.002)

        for comp in components:
            if id(comp) in seed_ids or comp["area"] < noise_threshold:
                continue
            nearest = min(
                range(len(seeds)),
                key=lambda i: abs(seeds[i]["center_x"] - comp["center_x"]),
            )
            groups[nearest].append(comp)

        return groups

    def _extract_component_frames(
        self, strip_no_bg: Image.Image, n_frames: int,
    ) -> list[Image.Image] | None:
        """Extract frames using connected-component grouping.

        Each group of components forms one frame. All frames share the same
        viewport dimensions (union of all group bboxes) so size and framing
        stay consistent without pixel-level registration.
        """
        components = self._find_connected_components(strip_no_bg)
        groups = self._group_components_into_frames(components, n_frames)
        if groups is None:
            return None

        width, height = strip_no_bg.size
        source_pixels = strip_no_bg.load()
        padding = 6

        # Compute per-group bboxes and a shared vertical range + max width
        group_bboxes = []
        for group in groups:
            min_x = min(c["bbox"][0] for c in group)
            min_y = min(c["bbox"][1] for c in group)
            max_x = max(c["bbox"][2] for c in group)
            max_y = max(c["bbox"][3] for c in group)
            group_bboxes.append((min_x, min_y, max_x, max_y))

        shared_top = max(0, min(b[1] for b in group_bboxes) - padding)
        shared_bottom = min(height, max(b[3] for b in group_bboxes) + padding)
        viewport_w = max(b[2] - b[0] for b in group_bboxes) + padding * 2
        viewport_h = max(1, shared_bottom - shared_top)

        frames: list[Image.Image] = []
        for group, bbox in zip(groups, group_bboxes):
            # Render only this group's pixels into a cropped image
            g_min_x = max(0, bbox[0] - padding)
            g_min_y = max(0, bbox[1] - padding)
            g_max_x = min(width, bbox[2] + padding)
            g_max_y = min(height, bbox[3] + padding)

            grouped = Image.new(
                "RGBA", (g_max_x - g_min_x, g_max_y - g_min_y), (0, 0, 0, 0),
            )
            gp = grouped.load()
            for comp in group:
                for idx in comp["pixels"]:
                    px = idx % width
                    py = idx // width
                    gp[px - g_min_x, py - g_min_y] = source_pixels[px, py]

            # Place into the shared viewport for consistent framing
            viewport = Image.new("RGBA", (viewport_w, viewport_h), (0, 0, 0, 0))
            left = (viewport_w - grouped.width) // 2
            viewport.alpha_composite(grouped, (max(0, left), g_min_y - shared_top))
            frames.append(self._fit_viewport_to_cell(viewport))

        return frames

    # ── Stable-slots extraction (Layer 2 fallback) ───────────────────

    def _extract_stable_slot_frames(
        self, strip_no_bg: Image.Image, n_frames: int,
    ) -> list[Image.Image]:
        """Equal-width split with a shared vertical viewport.

        All frames use the same crop height (union bbox top/bottom) and are
        scaled by the same viewport dimensions, preventing per-frame size
        popping while keeping the extraction simple and predictable.
        """
        bbox = strip_no_bg.getbbox()
        if bbox is None:
            return [Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
                    for _ in range(n_frames)]

        padding = 6
        shared_top = max(0, bbox[1] - padding)
        shared_bottom = min(strip_no_bg.height, bbox[3] + padding)
        slot_width = strip_no_bg.width / n_frames

        frames: list[Image.Image] = []
        for i in range(n_frames):
            left = round(i * slot_width)
            right = round((i + 1) * slot_width)
            crop = strip_no_bg.crop((left, shared_top, right, shared_bottom))
            frames.append(self._fit_viewport_to_cell(crop))

        return frames

    def _fit_viewport_to_cell(self, image: Image.Image) -> Image.Image:
        """Scale a viewport image to fit inside a 192×208 cell, centered.

        Uses LANCZOS resampling for smooth non-pixel styles; pixel art
        callers should use _scale_to_fit with NEAREST instead.
        """
        target = Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
        if image.getbbox() is None:
            return target

        viewport = image.copy()
        max_w = CELL_W - 10
        max_h = CELL_H - 10
        scale = min(max_w / viewport.width, max_h / viewport.height, 1.0)
        if scale != 1.0:
            viewport = viewport.resize(
                (max(1, round(viewport.width * scale)),
                 max(1, round(viewport.height * scale))),
                Image.NEAREST,
            )
        left = (CELL_W - viewport.width) // 2
        top = (CELL_H - viewport.height) // 2
        target.alpha_composite(viewport, (left, top))
        return target

    def _process_frame(self, img: Image.Image) -> Image.Image:
        no_bg = self._remove_green_background(img)

        bbox = no_bg.getbbox()
        if bbox:
            pad = 6
            bbox = (
                max(0, bbox[0] - pad),
                max(0, bbox[1] - pad),
                min(no_bg.width, bbox[2] + pad),
                min(no_bg.height, bbox[3] + pad),
            )
            no_bg = no_bg.crop(bbox)

        no_bg = self._scale_to_fit(no_bg, CELL_W - 20, CELL_H - 20)

        cell = Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
        offset = ((CELL_W - no_bg.width) // 2, (CELL_H - no_bg.height) // 2)
        cell.paste(no_bg, offset, no_bg)
        return cell

    def _remove_green_background(self, img: Image.Image) -> Image.Image:
        rgba = img.convert("RGBA")
        pixels = rgba.load()
        w, h = rgba.size

        for y in range(h):
            for x in range(w):
                r, g, b, a = pixels[x, y]
                # The generated background is intentionally green, but image
                # compression can leave very dark olive pixels beneath props
                # such as desks. Green dominance is more reliable than a
                # brightness cutoff for removing that spill.
                if g > r * 1.25 and g > b * 1.25:
                    pixels[x, y] = (0, 0, 0, 0)

        return rgba

    def _keep_largest_component(self, img: Image.Image) -> Image.Image:
        """Remove detached adjacent-frame fragments from a running pose."""
        alpha = img.getchannel("A")
        pixels = alpha.load()
        width, height = img.size
        visited = bytearray(width * height)
        largest: list[int] = []

        for y in range(height):
            for x in range(width):
                start = y * width + x
                if not pixels[x, y] or visited[start]:
                    continue

                component: list[int] = []
                stack = [start]
                visited[start] = 1
                while stack:
                    index = stack.pop()
                    component.append(index)
                    px, py = index % width, index // width
                    for ny in range(max(0, py - 1), min(height, py + 2)):
                        for nx in range(max(0, px - 1), min(width, px + 2)):
                            neighbor = ny * width + nx
                            if pixels[nx, ny] and not visited[neighbor]:
                                visited[neighbor] = 1
                                stack.append(neighbor)

                if len(component) > len(largest):
                    largest = component

        if not largest:
            return img

        keep = bytearray(width * height)
        for index in largest:
            keep[index] = 1
        rgba = img.copy()
        out_pixels = rgba.load()
        for y in range(height):
            for x in range(width):
                if not keep[y * width + x]:
                    out_pixels[x, y] = (0, 0, 0, 0)
        return rgba

    def _scale_to_fit(self, img: Image.Image, max_w: int, max_h: int) -> Image.Image:
        w, h = img.size
        if w == 0 or h == 0:
            return img

        ratio = min(max_w / w, max_h / h)
        if ratio >= 1.0:
            return img

        new_w = max(1, int(w * ratio))
        new_h = max(1, int(h * ratio))
        return img.resize((new_w, new_h), Image.NEAREST)

    def _fit_to_cell(self, img: Image.Image) -> Image.Image:
        return self._process_frame(img)

    # ── Atlas composition ────────────────────────────────────────────

    def _compose_atlas(
        self, strips: dict[PetAnimationName, list[Image.Image]], row_order: list[PetAnimationName]
    ) -> Image.Image:
        atlas = Image.new("RGBA", (ATLAS_W, CELL_H * len(row_order)), (0, 0, 0, 0))

        for row_idx, row_name in enumerate(row_order):
            frames = strips.get(row_name, [])
            for col_idx, frame in enumerate(frames):
                if col_idx >= COLS:
                    break
                x = col_idx * CELL_W
                y = row_idx * CELL_H
                atlas.paste(frame, (x, y), frame)

        return atlas

    # ── Style descriptors ────────────────────────────────────────────

    def _style_descriptor(self, style: str) -> str:
        styles = {
            "pixel": "pixel art, 16-bit retro game style, crisp pixels, limited color palette",
            "plush": "plush toy style, soft fabric texture, cute stuffed animal",
            "clay": "claymation style, clay texture, stop-motion puppet look",
            "sticker": "sticker style, bold outlines, flat colors, die-cut look",
            "flat-vector": "flat vector illustration, clean shapes, minimal shading",
            "anime": "anime style, cel-shaded, expressive eyes",
            "chibi": "chibi style, big head, small body, super deformed",
        }
        return styles.get(style, styles["pixel"])

    # ── Layout guide generation ──────────────────────────────────────

    def _generate_layout_guide(
        self, pet_id: str, row: PetAnimationName, n_frames: int,
    ) -> str | None:
        """Generate a visual layout guide showing expected frame positions.

        Creates a horizontal strip with N labelled cells on a solid green
        background. The guide is passed to the image model as a construction
        reference so it can follow the correct frame count, spacing, and
        safe padding without drawing visible guide elements in the output.
        """
        from PIL import ImageDraw

        cell_gap = 16
        guide_w = CELL_W * n_frames + cell_gap * (n_frames + 1)
        guide_h = CELL_H + cell_gap * 2
        guide = Image.new("RGBA", (guide_w, guide_h), (0, 255, 0, 255))
        draw = ImageDraw.Draw(guide)

        for i in range(n_frames):
            x = cell_gap + i * (CELL_W + cell_gap)
            y = cell_gap
            draw.rectangle(
                (x, y, x + CELL_W - 1, y + CELL_H - 1),
                outline=(200, 0, 200, 255), width=2,
            )
            # Frame number in top-left corner
            draw.text((x + 6, y + 4), f"{i + 1}", fill=(200, 0, 200, 255))

        path = self.store.original_path(pet_id, f"layout-guide-{row.value}.png")
        path.parent.mkdir(parents=True, exist_ok=True)
        guide.save(path, "PNG")
        return str(path)

    # ── Database persistence ─────────────────────────────────────────

    async def _persist_to_db(self, pet_id: str, config: PetConfig, user_id: int) -> None:
        from sqlalchemy import select

        from crabagent.core.database import PetPackage, async_session_factory

        async with async_session_factory() as session:
            result = await session.execute(
                select(PetPackage).where(
                    (PetPackage.pet_id == pet_id) & (PetPackage.user_id == user_id)
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.display_name = config.displayName
                existing.description = config.description
                existing.spritesheet_filename = config.spritesheetPath
                existing.config_json = config.model_dump_json()
            else:
                session.add(
                    PetPackage(
                        user_id=user_id,
                        pet_id=pet_id,
                        display_name=config.displayName,
                        description=config.description,
                        spritesheet_filename=config.spritesheetPath,
                        config_json=config.model_dump_json(),
                        is_builtin=False,
                    )
                )
            await session.commit()

    async def _write_error_package(self, pet_id: str, prompt: str, error: str) -> None:
        config = PetConfig(
            id=pet_id,
            displayName=pet_id,
            description=f"[ERROR] {error}",
            type="spritesheet",
        )
        self.store.write_config(pet_id, config.model_dump(mode="json"))
        logger.error("Pet %s generation error package written: %s", pet_id, error)
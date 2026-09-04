from __future__ import annotations

import base64
import io
import json
import logging
import mimetypes
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"})


def is_image_path(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_SUFFIXES and path.is_file()


def image_file_to_block(path: Path, max_bytes: int = 1_500_000) -> dict[str, Any] | None:
    """Encode an image for an LLM, resizing it when the source is too large."""
    if max_bytes <= 0:
        return None
    try:
        raw = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        if len(raw) > max_bytes or mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            raw, mime = _resize_image(raw, max_bytes)
        encoded = base64.b64encode(raw).decode("ascii")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{encoded}"},
            "file_path": str(path),
            "mime": mime,
            "size_kb": round(len(raw) / 1024, 1),
        }
    except Exception:
        logger.debug("Unable to encode image for multimodal input: %s", path, exc_info=True)
        return None


def _resize_image(raw: bytes, max_bytes: int) -> tuple[bytes, str]:
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(raw)) as source:
        image = ImageOps.exif_transpose(source)
        if getattr(image, "is_animated", False):
            image.seek(0)
        image = image.convert("RGB")

        for max_dimension in (2048, 1600, 1280, 1024, 768, 512):
            candidate = image.copy()
            candidate.thumbnail((max_dimension, max_dimension))
            for quality in (88, 78, 68, 55):
                output = io.BytesIO()
                candidate.save(output, format="JPEG", quality=quality, optimize=True)
                data = output.getvalue()
                if len(data) <= max_bytes:
                    return data, "image/jpeg"

        output = io.BytesIO()
        candidate.save(output, format="JPEG", quality=45, optimize=True)
        return output.getvalue(), "image/jpeg"


def attach_images_from_tool_result(result: object, context: Any) -> object:
    """Embed local image paths found in structured built-in tool output."""
    payload = result
    if isinstance(result, str):
        try:
            payload = json.loads(result)
        except (TypeError, ValueError):
            return result
    if not isinstance(payload, dict):
        return result

    candidates: list[str] = []
    images = payload.get("images", [])
    if isinstance(images, list):
        for image in images:
            if isinstance(image, dict) and image.get("path"):
                candidates.append(str(image["path"]))
    files = payload.get("files", [])
    if isinstance(files, list):
        for path in files:
            if isinstance(path, str):
                candidates.append(path)

    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    blocks: list[dict[str, Any]] = [{"type": "text", "text": text}]
    seen: set[Path] = set()
    workspace = Path(getattr(context, "workspace", Path.cwd()))
    for value in candidates[:4]:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = workspace / path
        path = path.resolve()
        if path in seen or not is_image_path(path):
            continue
        seen.add(path)
        block = image_file_to_block(path)
        if block:
            blocks.append(block)
    return blocks if len(blocks) > 1 else result


def stringify_tool_result(result: object) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, (dict, list)):
        return json.dumps(result, ensure_ascii=False, default=str)
    return str(result)


def split_multimodal_tool_result(result: object) -> tuple[str, list[dict[str, Any]]]:
    """Keep tool protocol text-only and return image blocks for a user-role follow-up."""
    if not isinstance(result, list):
        return stringify_tool_result(result), []

    text_parts: list[str] = []
    images: list[dict[str, Any]] = []
    for block in result:
        if isinstance(block, str):
            text_parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(str(block.get("text", "")))
        elif isinstance(block, dict) and block.get("type") == "image_url":
            image_url = block.get("image_url")
            if isinstance(image_url, dict) and image_url.get("url"):
                images.append(block)

    text = "\n".join(part for part in text_parts if part).strip()
    if images and not text:
        text = f"Returned {len(images)} image(s); visual content is attached in the next user message."
    return text, images

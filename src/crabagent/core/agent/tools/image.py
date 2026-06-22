"""
image_generate tool — AI image generation via litellm.

Supported providers:
- ChatGPT subscription (chatgpt/image-2, chatgpt/gpt-image-2, chatgpt/chatgpt-image-latest)
- OpenAI API (gpt-image-2, gpt-image-1, dall-e-3, dall-e-2)
- Others: auto-detected via litellm model_cost registry

Images are saved to .crabagent/assets/images/ in the workspace.
Returns structured JSON so frontend and downstream tools can consume results.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path

from crabagent.core.agent.tools.registry import registry

logger = logging.getLogger(__name__)

# ── Provider → default image model mapping ─────────────────────────────
_CHATGPT_IMAGE_MODELS = [
    "image-2",
    "gpt-image-2",
    "chatgpt-image-latest",
]
_OPENAI_IMAGE_MODELS = [
    "gpt-image-2",
    "gpt-image-1.5",
    "gpt-image-1",
    "dall-e-3",
    "dall-e-2",
]
_VALID_SIZES = {"1024x1024", "1024x1536", "1536x1024", "1792x1024", "1024x1792"}
_VALID_QUALITIES = {"auto", "standard", "hd", "high", "medium", "low"}


def _resolve_model(provider_type: str, model: str) -> str:
    """Resolve the full litellm model name from user-facing model + provider."""
    if "/" in model:
        return model
    if provider_type == "chatgpt":
        return f"chatgpt/{model}"
    if provider_type == "openai":
        return model
    return model


def _image_dir(context) -> Path:
    """Ensure .crabagent/assets/images/ exists in workspace and return it."""
    ws = context.workspace.resolve() if hasattr(context, "workspace") else Path.cwd()
    img_dir = ws / ".crabagent" / "assets" / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    return img_dir


def _save_image(b64_data: str, img_dir: Path, stem: str, index: int) -> Path:
    """Decode base64 image data and save as PNG. Returns the file path."""
    # Strip data:image prefix if present
    if "," in b64_data and b64_data.startswith("data:"):
        b64_data = b64_data.split(",", 1)[1]
    raw = base64.b64decode(b64_data)
    suffix = "-1" if index == 0 else f"-{index + 1}"
    filepath = img_dir / f"{stem}{suffix}.png"
    filepath.write_bytes(raw)
    return filepath


def _save_url_image(url: str, img_dir: Path, stem: str, index: int) -> Path | None:
    """Download image from URL and save. Returns path or None on failure."""
    import asyncio
    import ssl

    import httpx

    from crabagent.core.proxy import resolve_category_proxy

    async def _dl():
        client_kwargs = {"timeout": 60.0, "follow_redirects": True}
        # Skip SSL verify for some image CDNs that have cert issues
        try:
            proxy = await resolve_category_proxy("image")
            if proxy:
                client_kwargs["proxy"] = proxy
        except Exception:
            pass
        # Use a context that doesn't enforce strict SSL for image CDNs
        ssl_ctx = ssl.create_default_context()
        async with httpx.AsyncClient(verify=ssl_ctx, **client_kwargs) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                fut = pool.submit(asyncio.run, _dl())
                content = fut.result(timeout=60)
        else:
            content = asyncio.run(_dl())
    except Exception as e:
        logger.warning("Failed to download image from URL %s: %s", url[:80], e)
        return None

    suffix = "-1" if index == 0 else f"-{index + 1}"
    filepath = img_dir / f"{stem}{suffix}.png"
    filepath.write_bytes(content)
    return filepath


def _guess_extension(content_type: str | None) -> str:
    """Guess file extension from Content-Type header."""
    if not content_type:
        return ".png"
    ct = content_type.lower()
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"
    if "webp" in ct:
        return ".webp"
    if "avif" in ct:
        return ".avif"
    return ".png"


# ── Tool registration ───────────────────────────────────────────────────

@registry.register(
    name="image_generate",
    description=(
        "Generate images using AI image models. "
        "Use this tool when the user asks to create, generate, or design images, "
        "logos, icons, posters, illustrations, cover images, product images, etc. "
        "The tool automatically selects the best available image model based on "
        "the current provider configuration (ChatGPT subscription, OpenAI API, etc.). "
        "Generated images are saved to the workspace. "
        "Returns structured results with file paths so images can be previewed "
        "and used in documents, presentations, or further editing."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": (
                    "Detailed image description. Be specific about subject, style, colors, "
                    "composition, lighting, mood. English prompts generally produce better results."
                ),
            },
            "size": {
                "type": "string",
                "description": (
                    "Image size. Common values: 1024x1024 (square), 1024x1536 (portrait), "
                    "1536x1024 (landscape). Default: 1024x1024."
                ),
                "default": "1024x1024",
            },
            "n": {
                "type": "integer",
                "description": "Number of images to generate (1-4). Default: 1.",
                "default": 1,
            },
            "quality": {
                "type": "string",
                "description": (
                    "Quality level: auto (best available), standard, hd, high, medium, low. "
                    "Default: auto."
                ),
                "default": "auto",
            },
            "style": {
                "type": "string",
                "description": (
                    "Visual style guidance. E.g. 'photorealistic', 'illustration', "
                    "'vector', 'watercolor', 'cyberpunk', 'minimalist'. "
                    "Leave empty for model default."
                ),
                "default": "",
            },
            "output_name": {
                "type": "string",
                "description": (
                    "Base filename for saved images (without extension). "
                    "E.g. 'logo', 'poster-hero'. Auto-generated from timestamp if empty."
                ),
                "default": "",
            },
        },
        "required": ["prompt"],
    },
)
async def image_generate(
    prompt: str,
    size: str = "1024x1024",
    n: int = 1,
    quality: str = "auto",
    style: str = "",
    output_name: str = "",
    context=None,
) -> str:
    """Generate images using the configured AI provider."""
    import litellm

    # ── Resolve provider ─────────────────────────────────────────────
    provider_type = "openai"
    provider_name = "default"
    if context is not None:
        try:
            from crabagent.core.provider_store import get_default_provider, get_provider, list_providers

            pname = getattr(context, "provider_name", None)
            pinfo = None
            if pname:
                pinfo = await get_provider(pname)
            if not pinfo:
                pinfo = await get_default_provider()

            # If current provider doesn't support image generation, find one that does.
            # ChatGPT subscription and OpenAI providers support image generation.
            _IMAGE_CAPABLE = {"chatgpt", "openai"}
            if pinfo and pinfo.provider_type not in _IMAGE_CAPABLE:
                # Try default provider first, then scan for any chatgpt/openai provider
                default = await get_default_provider()
                if default and default.provider_type in _IMAGE_CAPABLE and default.name != pinfo.name:
                    pinfo = default
                else:
                    all_providers = await list_providers()
                    for p in all_providers:
                        if p.provider_type in _IMAGE_CAPABLE and p.enabled:
                            pinfo = p
                            break
            if pinfo:
                provider_type = pinfo.provider_type
                provider_name = pinfo.name
        except Exception:
            pass

    # ── Determine model ──────────────────────────────────────────────
    if provider_type == "chatgpt":
        model = "chatgpt/image-2"
        # Clamp n for chatgpt provider (typically max 1-2)
        if n > 2:
            n = 2
    elif provider_type == "openai":
        model = "gpt-image-2"
        if n > 4:
            n = 4
    else:
        model = "gpt-image-2"
        if n > 4:
            n = 4

    # ── Validate / normalise params ──────────────────────────────────
    if size not in _VALID_SIZES:
        size = "1024x1024"
    if quality not in _VALID_QUALITIES:
        quality = "auto"
    if n < 1:
        n = 1

    # Build prompt with style if provided
    full_prompt = prompt
    if style:
        full_prompt = f"{style} style. {prompt}"

    # ── Generate image ───────────────────────────────────────────────
    try:
        t0 = time.monotonic()
        resp = await litellm.aimage_generation(
            model=model,
            prompt=full_prompt,
            size=size,
            n=n,
            quality=quality,
            timeout=120,
        )
        elapsed = time.monotonic() - t0
        logger.info("image_generate: %s in %.1fs, provider=%s", model, elapsed, provider_name)
    except Exception as e:
        logger.error("image_generate failed: %s", e)
        return json.dumps({
            "error": f"Image generation failed: {e}",
            "provider": provider_name,
            "model": model,
            "prompt": prompt,
        }, ensure_ascii=False)

    # ── Parse response ───────────────────────────────────────────────
    data = resp.get("data") if isinstance(resp, dict) else getattr(resp, "data", None)
    if not data:
        return json.dumps({
            "error": "No image data in response",
            "provider": provider_name,
            "model": model,
        }, ensure_ascii=False)

    revised_prompt = None
    if isinstance(data, list) and len(data) > 0:
        first = data[0]
        if isinstance(first, dict):
            revised_prompt = first.get("revised_prompt")
        elif hasattr(first, "revised_prompt"):
            revised_prompt = first.revised_prompt

    # ── Save images ──────────────────────────────────────────────────
    img_dir = _image_dir(context) if context else Path.cwd() / ".crabagent" / "assets" / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    stem = output_name or f"image-{time.strftime('%Y%m%d-%H%M%S')}"
    # Sanitise stem for filesystem
    stem = "".join(c if c.isalnum() or c in "._- " else "_" for c in stem).strip().replace(" ", "-")
    if not stem:
        stem = f"image-{time.strftime('%Y%m%d-%H%M%S')}"

    saved: list[dict] = []
    for i, item in enumerate(data):
        item_dict = item if isinstance(item, dict) else vars(item) if hasattr(item, "__dict__") else {}
        b64 = item_dict.get("b64_json", "")
        url = item_dict.get("url", "")

        filepath = None
        if b64:
            filepath = _save_image(b64, img_dir, stem, i)
        elif url:
            filepath = _save_url_image(url, img_dir, stem, i)

        entry = {
            "index": i + 1,
            "prompt": full_prompt[:500],
            "size": size,
            "model": model,
        }
        if filepath:
            entry["path"] = str(filepath)
            entry["filename"] = filepath.name
        if revised_prompt:
            entry["revised_prompt"] = revised_prompt
        if url and not b64:
            entry["url"] = url
        saved.append(entry)

    # ── Save metadata sidecar ────────────────────────────────────────
    meta = {
        "prompt": full_prompt,
        "revised_prompt": revised_prompt,
        "model": model,
        "provider": provider_name,
        "provider_type": provider_type,
        "size": size,
        "quality": quality,
        "n": n,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "files": [s.get("path", "") or s.get("url", "") for s in saved],
    }
    meta_file = img_dir / f"{stem}.json"
    try:
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    except OSError:
        pass

    # ── Return structured result ─────────────────────────────────────
    result = {
        "generated": len(saved),
        "provider": provider_name,
        "model": model,
        "size": size,
        "quality": quality,
        "images": saved,
        "meta_file": str(meta_file),
        "workspace_relative": f".crabagent/assets/images/{stem}*.png",
    }
    return json.dumps(result, ensure_ascii=False, indent=2)

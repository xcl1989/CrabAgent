from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import Message


async def save_message(
    db: AsyncSession,
    conversation_id: int,
    sequence: int,
    role: str,
    content: str = "",
    tool_calls: str | None = None,
    tool_call_id: str | None = None,
    name: str | None = None,
    reasoning_content: str | None = None,
    branch_id: str = "main",
    parent_id: int | None = None,
    agent: str = "default",
) -> Message:
    msg = Message(
        conversation_id=conversation_id,
        sequence=sequence,
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
        name=name,
        reasoning_content=reasoning_content,
        branch_id=branch_id,
        parent_id=parent_id,
        agent=agent,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


async def get_messages(
    db: AsyncSession,
    conversation_id: int,
    limit: int | None = None,
    offset: int = 0,
    branch_id: str | None = None,
    include_compressed: bool = False,
) -> list[Message]:
    stmt = select(Message).where(Message.conversation_id == conversation_id)
    if branch_id is not None:
        stmt = stmt.where(Message.branch_id == branch_id)
    if not include_compressed:
        stmt = stmt.where(Message.compressed == False)  # noqa: E712
    stmt = stmt.order_by(Message.sequence.desc(), Message.id.desc())
    if offset:
        stmt = stmt.offset(offset)
    if limit:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    msgs = list(result.scalars().all())
    msgs.reverse()
    return msgs


async def delete_messages(db: AsyncSession, conversation_id: int) -> int:
    from sqlalchemy import delete as sa_delete

    result = await db.execute(sa_delete(Message).where(Message.conversation_id == conversation_id))
    await db.commit()
    return result.rowcount


def message_to_dict(msg: Message) -> dict:
    d: dict = {"role": msg.role}
    # agent_switch / compress / experience / workspace → user for the LLM
    if d["role"] in ("agent_switch", "compress", "experience", "workspace"):
        d["role"] = "user"

    if msg.content:
        if msg.content.startswith("["):
            try:
                d["content"] = json.loads(msg.content)
            except json.JSONDecodeError:
                d["content"] = msg.content
        else:
            d["content"] = msg.content
    else:
        d["content"] = None

    if msg.tool_calls:
        try:
            d["tool_calls"] = json.loads(msg.tool_calls)
        except json.JSONDecodeError:
            d["tool_calls"] = None

    if msg.tool_call_id:
        d["tool_call_id"] = msg.tool_call_id

    if msg.name:
        d["name"] = msg.name

    if msg.reasoning_content:
        d["reasoning_content"] = msg.reasoning_content

    return d


def _try_inline_image(path_str: str) -> str | None:
    """Read an image file and return a base64 data URL, or None on failure."""
    import base64
    from pathlib import Path

    try:
        p = Path(path_str)
        if not p.is_file():
            return None
        ext = p.suffix.lower().lstrip(".")
        mime_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "gif": "gif", "avif": "avif"}
        mime = mime_map.get(ext, "png")
        b64 = base64.b64encode(p.read_bytes()).decode()
        return f"data:image/{mime};base64,{b64}"
    except Exception:
        return None


def _strip_base64_images(content: str) -> tuple[str, list[str]]:
    """Remove base64 image data from message content to keep list responses light.

    Handles two patterns:
    1. JSON array content with image_url blocks (user/tool multimodal messages)
    2. screenshot role messages where content is a file path (image loaded separately)

    Returns (stripped_content, list_of_image_data_urls).
    """
    if not content:
        return content, []

    images: list[str] = []

    # Pattern 1: JSON array with image_url blocks containing data: URLs
    if content.startswith("["):
        try:
            blocks = json.loads(content)
            if isinstance(blocks, list):
                modified = False
                for block in blocks:
                    if isinstance(block, dict) and block.get("type") == "image_url":
                        url = block.get("image_url", {}).get("url", "")
                        if url.startswith("data:image/"):
                            images.append(url)
                            block["image_url"]["url"] = ""  # strip the heavy data
                            modified = True
                if modified:
                    return json.dumps(blocks, ensure_ascii=False), images
        except (json.JSONDecodeError, TypeError):
            pass

    return content, images


def message_to_response(msg: Message, strip_images: bool = True) -> dict:
    d: dict = {
        "id": msg.id,
        "sequence": msg.sequence,
        "role": msg.role,
        "content": msg.content or "",
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }

    # Strip base64 image data from content for list views (major perf win).
    # Frontend lazily fetches images via /messages/{id}/images endpoint.
    if strip_images and d["content"]:
        d["content"], extracted = _strip_base64_images(d["content"])
        if extracted:
            d["has_images"] = True

    # Screenshot messages: don't inline base64 in list view; mark has_images.
    if msg.role == "screenshot" and msg.content:
        if strip_images:
            d["has_images"] = True
        else:
            data_url = _try_inline_image(msg.content)
            if data_url:
                d["image_data"] = data_url

    if msg.tool_calls:
        try:
            d["tool_calls"] = json.loads(msg.tool_calls)
        except json.JSONDecodeError:
            d["tool_calls"] = None
    if msg.tool_call_id:
        d["tool_call_id"] = msg.tool_call_id
    if msg.name:
        d["name"] = msg.name
    if msg.reasoning_content:
        d["reasoning_content"] = msg.reasoning_content
    d["branch_id"] = msg.branch_id or "main"
    d["parent_id"] = msg.parent_id
    d["compressed"] = bool(msg.compressed)
    return d

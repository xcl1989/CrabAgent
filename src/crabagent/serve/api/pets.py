"""API routes for desktop pet packages.

Supports listing, installing, and deleting Codex-compatible pet packages, plus
downloading the spritesheet asset.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import PetPackage, User, get_db
from crabagent.core.pets import PetAnimationName, PetConfig, PetStore, get_pet_store
from crabagent.core.pets.generation import PetGenerationService, get_generation_progress
from crabagent.serve.deps import get_current_user

router = APIRouter(prefix="/pets", tags=["pets"])


async def _resolve_user(
    request: Request,
    token: str = "",
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve user from header or query-param token.

    Supports both the standard ``Authorization: Bearer <jwt>`` header and a
    ``?token=<jwt>`` query parameter so that ``<img>`` tags in the pet
    window can load authenticated spritesheet URLs.
    """
    raw = token
    if not raw:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            raw = auth[7:]

    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    from crabagent.serve.services.auth import decode_access_token, get_user_by_id

    payload = decode_access_token(raw)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    user = await get_user_by_id(db, user_id)
    if not user or not user.enabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


class PetListItem(BaseModel):
    id: str
    displayName: str
    description: str
    is_builtin: bool
    created_at: str


class PetDetail(BaseModel):
    id: str
    displayName: str
    description: str
    spritesheetPath: str
    width: int
    height: int
    columns: int
    rows: int
    frame_counts: dict[str, int]
    frame_rates: dict[str, int]
    type: str
    is_builtin: bool


class CreatePetRequest(BaseModel):
    id: str
    displayName: str
    description: str = ""
    spritesheetPath: str = "spritesheet.webp"
    width: int = 192
    height: int = 208
    columns: int = 8
    rows: int = 9
    frame_counts: dict[str, int] | None = None
    frame_rates: dict[str, int] | None = None
    type: str = "spritesheet"


class GeneratePetRequest(BaseModel):
    prompt: str
    style: str = "pixel"


class GeneratePetResponse(BaseModel):
    id: str
    displayName: str
    status: str


class GenerationStatusResponse(BaseModel):
    id: str
    status: str  # generating | ready | error
    displayName: str
    description: str


def _store() -> PetStore:
    return get_pet_store()


def _spritesheet_disk_path(pet: PetPackage, store: PetStore) -> Path:
    return store.spritesheet_path(pet.pet_id, pet.spritesheet_filename)


def _to_detail(pet: PetPackage) -> PetDetail:
    try:
        config = PetConfig.model_validate_json(pet.config_json)
    except Exception:
        config = PetConfig(
            id=pet.pet_id,
            displayName=pet.display_name,
            description=pet.description,
            spritesheetPath=pet.spritesheet_filename,
        )
    return PetDetail(
        id=pet.pet_id,
        displayName=config.displayName or pet.display_name,
        description=config.description or pet.description,
        spritesheetPath=config.spritesheetPath,
        width=config.width,
        height=config.height,
        columns=config.columns,
        rows=config.rows,
        frame_counts={k.value: v for k, v in config.frame_counts.items()},
        frame_rates={k.value: v for k, v in config.frame_rates.items()},
        type=config.type,
        is_builtin=pet.is_builtin,
    )


@router.get("", response_model=list[PetListItem])
async def list_pets(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PetPackage).where(
            (PetPackage.user_id == user.id) | (PetPackage.is_builtin == True)  # noqa: E712
        )
    )
    rows = result.scalars().all()
    return [
        PetListItem(
            id=r.pet_id,
            displayName=r.display_name,
            description=r.description,
            is_builtin=r.is_builtin,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@router.get("/{pet_id}", response_model=PetDetail)
async def get_pet(
    pet_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PetPackage).where(
            (PetPackage.pet_id == pet_id)
            & ((PetPackage.user_id == user.id) | (PetPackage.is_builtin == True))  # noqa: E712
        )
    )
    pet = result.scalar_one_or_none()
    if not pet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pet not found")
    return _to_detail(pet)


@router.get("/{pet_id}/spritesheet")
async def get_pet_spritesheet(
    pet_id: str,
    request: Request,
    token: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Serve the spritesheet image.

    Authentication supports both header and ``?token=`` query param so
    ``<img>`` tags work in the pet Electron window.
    """
    user = await _resolve_user(request, token, db)
    result = await db.execute(
        select(PetPackage).where(
            (PetPackage.pet_id == pet_id)
            & ((PetPackage.user_id == user.id) | (PetPackage.is_builtin == True))  # noqa: E712
        )
    )
    pet = result.scalar_one_or_none()
    if not pet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pet not found")

    store = _store()
    path = _spritesheet_disk_path(pet, store)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Spritesheet not found on disk",
        )
    # Detect media type from extension.
    suffix = path.suffix.lower()
    media_type = "image/png" if suffix == ".png" else "image/webp"
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.post("", response_model=PetDetail, status_code=status.HTTP_201_CREATED)
async def create_pet(
    req: CreatePetRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(PetPackage).where(
            (PetPackage.pet_id == req.id) & (PetPackage.user_id == user.id)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pet with this id already exists",
        )

    config = PetConfig(
        id=req.id,
        displayName=req.displayName,
        description=req.description,
        spritesheetPath=req.spritesheetPath,
        width=req.width,
        height=req.height,
        columns=req.columns,
        rows=req.rows,
        type=req.type,  # type: ignore[arg-type]
    )
    if req.frame_counts:
        config.frame_counts = {PetAnimationName(k): v for k, v in req.frame_counts.items()}  # type: ignore[misc]
    if req.frame_rates:
        config.frame_rates = {PetAnimationName(k): v for k, v in req.frame_rates.items()}  # type: ignore[misc]

    store = _store()
    store.write_config(req.id, config.model_dump(mode="json"))

    db.add(
        PetPackage(
            user_id=user.id,
            pet_id=req.id,
            display_name=req.displayName,
            description=req.description,
            spritesheet_filename=req.spritesheetPath,
            config_json=config.model_dump_json(),
            is_builtin=False,
        )
    )
    await db.commit()
    return _to_detail(
        PetPackage(
            pet_id=req.id,
            display_name=req.displayName,
            description=req.description,
            spritesheet_filename=req.spritesheetPath,
            config_json=config.model_dump_json(),
            is_builtin=False,
        )
    )


@router.post("/{pet_id}/upload")
async def upload_spritesheet(
    pet_id: str,
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PetPackage).where(
            (PetPackage.pet_id == pet_id)
            & (PetPackage.user_id == user.id)
            & (PetPackage.is_builtin == False)  # noqa: E712
        )
    )
    pet = result.scalar_one_or_none()
    if not pet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pet not found")

    filename = file.filename or "spritesheet.webp"
    if not filename.lower().endswith((".webp", ".png")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .webp and .png spritesheets are supported",
        )

    store = _store()
    data = await file.read()
    store.write_spritesheet(pet_id, data, filename)

    pet.spritesheet_filename = filename
    config = PetConfig.model_validate_json(pet.config_json)
    config.spritesheetPath = filename
    pet.config_json = config.model_dump_json()
    await db.commit()

    return {"ok": True, "spritesheetPath": filename}


@router.post("/generate", response_model=GeneratePetResponse, status_code=status.HTTP_202_ACCEPTED)
async def generate_pet(
    prompt: str = Form(...),
    style: str = Form("pixel"),
    preserve_reference_style: bool = Form(False),
    reference: UploadFile | None = File(None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start an async pet generation job.

    If *reference* is provided, the uploaded photo is used as the base
    character design instead of generating one from scratch.
    """
    pet_id = f"gen-{uuid.uuid4().hex[:8]}"
    service = PetGenerationService(store=_store())

    # Save the reference image (if any) to the package folder.
    ref_path: Path | None = None
    if reference and reference.filename:
        ref_bytes = await reference.read()
        if ref_bytes:
            pkg_dir = _store().package_dir(pet_id)
            pkg_dir.mkdir(parents=True, exist_ok=True)
            ext = Path(reference.filename).suffix.lower() or ".png"
            ref_path = pkg_dir / f"reference{ext}"
            ref_path.write_bytes(ref_bytes)

    import asyncio

    asyncio.create_task(
        service.generate_from_prompt(
            pet_id,
            prompt,
            style=style,
            user_id=user.id,
            reference_image_path=str(ref_path) if ref_path else None,
            preserve_reference_style=preserve_reference_style,
        )
    )
    return GeneratePetResponse(
        id=pet_id,
        displayName=pet_id,
        status="generating",
    )


@router.get("/generate/{pet_id}/status", response_model=GenerationStatusResponse)
async def get_generation_status(
    pet_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check whether a generation job has finished and the package is ready."""
    # First check the in-memory progress tracker for live status.
    progress = get_generation_progress(pet_id)
    if progress:
        return GenerationStatusResponse(
            id=pet_id,
            status=progress.get("status", "generating"),
            displayName=pet_id,
            description=progress.get("step_label", ""),
        )

    # Fallback: check the filesystem and database.
    result = await db.execute(
        select(PetPackage).where(
            (PetPackage.pet_id == pet_id) & (PetPackage.user_id == user.id)
        )
    )
    pet = result.scalar_one_or_none()

    store = _store()
    has_spritesheet = store.spritesheet_path(pet_id).exists()
    config = store.read_config(pet_id)
    description = config.get("description", "")
    is_error = description.startswith("[ERROR]")

    if pet and has_spritesheet and not is_error:
        return GenerationStatusResponse(
            id=pet_id, status="ready", displayName=pet.display_name, description=pet.description,
        )
    elif is_error:
        return GenerationStatusResponse(
            id=pet_id, status="error", displayName=pet_id, description=description,
        )
    else:
        return GenerationStatusResponse(
            id=pet_id, status="generating", displayName=pet_id, description=description or "Generating…",
        )


@router.get("/generate/{pet_id}/progress")
async def get_generation_progress_sse(
    pet_id: str,
    request: Request,
    token: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Server-Sent Events stream for real-time generation progress."""
    import asyncio
    import json

    from starlette.responses import StreamingResponse

    await _resolve_user(request, token, db)

    async def event_stream():
        last_snapshot = None
        while True:
            if await request.is_disconnected():
                break

            progress = get_generation_progress(pet_id)
            if progress:
                snapshot = json.dumps(progress, ensure_ascii=False, default=str)
                if snapshot != last_snapshot:
                    last_snapshot = snapshot
                    yield f"data: {snapshot}\n\n"

                status = progress.get("status", "running")
                if status in ("done", "error"):
                    await asyncio.sleep(0.5)
                    yield f"data: {snapshot}\n\n"
                    break
            else:
                store = _store()
                if store.spritesheet_path(pet_id).exists():
                    yield f'data: {json.dumps({"status": "done", "step_label": "完成"})}\n\n'
                else:
                    yield f'data: {json.dumps({"status": "idle", "step_label": "等待开始"})}\n\n'
                break

            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/{pet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pet(
    pet_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PetPackage).where(
            (PetPackage.pet_id == pet_id)
            & (PetPackage.user_id == user.id)
            & (PetPackage.is_builtin == False)  # noqa: E712
        )
    )
    pet = result.scalar_one_or_none()
    if not pet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pet not found")

    _store().delete_package(pet_id)
    await db.delete(pet)
    await db.commit()
    return None
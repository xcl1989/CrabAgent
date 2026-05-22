from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import Notification, User, get_db
from crabagent.serve.deps import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationResponse(BaseModel):
    id: int
    title: str
    body: str
    conversation_id: str
    read: bool
    created_at: str


def _to_response(n: Notification) -> NotificationResponse:
    return NotificationResponse(
        id=n.id,
        title=n.title,
        body=n.body or "",
        conversation_id=n.conversation_id or "",
        read=n.read,
        created_at=n.created_at.isoformat() if n.created_at else "",
    )


@router.get("", response_model=list[NotificationResponse])
async def list_notifications(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    return [_to_response(r) for r in result.scalars().all()]


@router.get("/unread-count")
async def unread_count(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id,
            Notification.read.is_(False),
        )
    )
    return {"count": result.scalar() or 0}


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user.id,
        )
    )
    n = result.scalar_one_or_none()
    if not n:
        return {"status": "not_found"}
    n.read = True
    await db.commit()
    return {"status": "ok"}


@router.post("/read-all")
async def mark_all_read(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from sqlalchemy import update

    await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read.is_(False))
        .values(read=True)
    )
    await db.commit()
    return {"status": "ok"}
